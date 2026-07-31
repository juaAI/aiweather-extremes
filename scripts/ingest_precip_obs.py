"""Build a unified hourly precipitation observation panel for the paper countries.

No single public source covers the Track A window everywhere, so this pulls
three feeds onto one schema:

* GHCNh — NOAA's successor to the Integrated Surface Database, read from the
  AWS open-data mirror because NCEI throttles bulk clients. Used for the nine
  countries whose national networks reach it intact.
* DWD Climate Data Center — one zip per station under
  ``hourly/precipitation/recent``, spanning roughly the last 500 days. ``R1``
  is the hourly total in mm and ``QN_8`` the quality level.
* Météo-France via data.gouv.fr — one gzipped CSV per département covering
  2025-2026, refreshed daily. ``RR1`` is the hourly total in mm and ``QRR1``
  the quality flag.

Germany and France need the national feeds because NOAA retired ISD with no
update past 2025-08-24, part-way through the window: that leaves GHCNh with a
single usable German station and none at all in France. Poland and Italy are
absent by design — IMGW publishes no hourly precipitation (only 6-hour
accumulations) and Italy has no national station archive.

All three feeds timestamp in UTC, so no conversion is needed. DWD and
Météo-France report strictly on the hour; a small number of GHCNh rows carry
off-hour timestamps from special observations and are kept as reported rather
than snapped to the hour, since which of the two to prefer is an analysis
decision. Raw downloads are
cached under ``data/cache/precip_obs`` so reruns are cheap and the script is
resumable after an interruption. Output is two parquets in ``data/derived``:
the station inventory and the station-hour observations, restricted to the
track window.

Run:  python scripts/ingest_precip_obs.py [--workers N] [--source ghcnh|dwd|meteofrance]
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests
import yaml

from qe_client import PROJECT_ROOT

DERIVED = PROJECT_ROOT / "data" / "derived"
CACHE = PROJECT_ROOT / "data" / "cache" / "precip_obs"
CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())

# NCEI's own host throttles hard after a couple of thousand requests; the AWS
# open-data mirror serves the identical files without limits.
GHCNH_S3 = "https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/access/by-year"
GHCNH_STATION_LIST = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network"
    "/hourly/doc/ghcnh-station-list.csv"
)
# Countries GHCNh still covers continuously; DE and FR come from national
# feeds instead, and PL and IT have no hourly source at all.
GHCNH_COUNTRIES = ["CH", "GB", "NO", "AT", "CZ", "ES", "NL", "BE", "DK"]

DWD_BASE = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany"
    "/climate/hourly/precipitation/recent"
)
DWD_STATION_LIST = f"{DWD_BASE}/RR_Stundenwerte_Beschreibung_Stationen.txt"
# data.gouv.fr dataset "Données climatologiques de base - horaires".
MF_DATASET = "6569b4473bedf2e7abad3b72"
MF_PERIOD = "2025-2026"

DEFAULT_WORKERS = 8
# DWD encodes missing values as -999 across every numeric column.
DWD_MISSING = -999.0
# GHCNh applies only basic quality control, and longer accumulations
# occasionally leak into the hourly column — they surface as impossible totals
# reported exactly on 00/06 UTC. Bound at the WMO world record for one-hour
# precipitation so genuine extremes survive but physically impossible values do
# not, following the absolute-limit check in WeatherReal (arXiv:2409.09371).
MAX_HOURLY_MM = 305.0

OBS_SCHEMA = ["station_id", "source", "country", "valid_time", "precip_mm", "quality"]
STATION_SCHEMA = ["station_id", "source", "country", "name", "lat", "lon", "elevation_m"]


def _window() -> tuple[datetime, datetime]:
    track = CONFIG["tracks"]["track_a"]
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return parse(track["start"]), parse(track["end"])


def _get(url: str, cache_name: str, timeout: int = 300) -> bytes | None:
    """Fetch a URL, caching the raw bytes on disk. Returns None on failure."""
    path = CACHE / cache_name
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200 or not response.content:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


# --------------------------------------------------------------------------
# GHCNh
# --------------------------------------------------------------------------


def ghcnh_stations() -> pl.DataFrame:
    """Station inventory for the countries GHCNh still covers."""
    raw = _get(GHCNH_STATION_LIST, "ghcnh/stations.csv", timeout=180)
    if raw is None:
        raise RuntimeError("could not fetch the GHCNh station list")
    frame = pl.read_csv(io.BytesIO(raw), infer_schema_length=0, encoding="utf8-lossy")
    return (
        frame.filter(pl.col("ISO_CODE").is_in(GHCNH_COUNTRIES))
        .select(
            ("GHCNh:" + pl.col("GHCN_ID")).alias("station_id"),
            pl.lit("ghcnh").alias("source"),
            pl.col("ISO_CODE").alias("country"),
            pl.col("NAME").str.strip_chars().alias("name"),
            pl.col("LATITUDE").cast(pl.Float64, strict=False).alias("lat"),
            pl.col("LONGITUDE").cast(pl.Float64, strict=False).alias("lon"),
            pl.col("ELEVATION").cast(pl.Float64, strict=False).alias("elevation_m"),
        )
        .unique(subset=["station_id"], keep="first")
    )


def ghcnh_observations(
    station_id: str, country: str, start: datetime, end: datetime
) -> pl.DataFrame | None:
    """Hourly totals for one GHCNh station, stitched across the two calendar years."""
    code = station_id.split(":", 1)[1]
    frames = []
    for year in range(start.year, end.year + 1):
        raw = _get(
            f"{GHCNH_S3}/{year}/parquet/GHCNh_{code}_{year}.parquet",
            f"ghcnh/{code}_{year}.parquet",
            timeout=120,
        )
        if raw is None:
            continue
        try:
            year_frame = pl.read_parquet(
                io.BytesIO(raw), columns=["DATE", "precipitation"]
            )
        except Exception:
            continue
        if year_frame.is_empty():
            continue
        frames.append(year_frame)
    if not frames:
        return None

    return (
        pl.concat(frames)
        .select(
            pl.lit(station_id).alias("station_id"),
            pl.lit("ghcnh").alias("source"),
            pl.lit(country).alias("country"),
            pl.col("DATE").cast(pl.String).str.to_datetime(
                "%Y-%m-%dT%H:%M:%S", time_zone="UTC", strict=False
            ).alias("valid_time"),
            pl.col("precipitation").cast(pl.Float64, strict=False).alias("precip_mm"),
            pl.lit(None, dtype=pl.String).alias("quality"),
        )
        .filter(
            pl.col("precip_mm").is_not_null(),
            pl.col("valid_time").is_not_null(),
            pl.col("valid_time") >= start,
            pl.col("valid_time") < end,
        )
    )


# --------------------------------------------------------------------------
# DWD
# --------------------------------------------------------------------------

# Fixed-ish columns: id, from, to, height, lat, lon, then name and state.
_DWD_STATION_RE = re.compile(
    r"^\s*(\d+)\s+(\d{8})\s+(\d{8})\s+(-?\d+)\s+([\d.-]+)\s+([\d.-]+)\s+(.+?)\s{2,}(\S.*?)\s*$"
)


def dwd_stations(start: datetime, end: datetime) -> pl.DataFrame:
    """Station inventory for stations whose record spans the track window."""
    raw = _get(DWD_STATION_LIST, "dwd/stations.txt", timeout=120)
    if raw is None:
        raise RuntimeError("could not fetch the DWD station list")
    rows = []
    for line in raw.decode("latin-1").splitlines()[2:]:
        match = _DWD_STATION_RE.match(line)
        if not match:
            continue
        station, since, until, height, lat, lon, name, _state = match.groups()
        if int(since) > int(start.strftime("%Y%m%d")):
            continue
        if int(until) < int(end.strftime("%Y%m%d")):
            continue
        rows.append(
            {
                "station_id": f"DWD:{station.zfill(5)}",
                "source": "dwd",
                "country": "DE",
                "name": name.strip(),
                "lat": float(lat),
                "lon": float(lon),
                "elevation_m": float(height),
            }
        )
    return pl.DataFrame(rows, schema=STATION_SCHEMA)


def dwd_observations(station_id: str, start: datetime, end: datetime) -> pl.DataFrame | None:
    """Hourly totals for one DWD station, or None when the station has no file."""
    code = station_id.split(":")[1]
    raw = _get(
        f"{DWD_BASE}/stundenwerte_RR_{code}_akt.zip", f"dwd/{code}.zip", timeout=120
    )
    if raw is None:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            member = next(
                (n for n in archive.namelist() if n.startswith("produkt_rr_stunde")), None
            )
            if member is None:
                return None
            payload = archive.read(member)
    except zipfile.BadZipFile:
        return None

    frame = pl.read_csv(
        io.BytesIO(payload), separator=";", infer_schema_length=0, encoding="utf8-lossy"
    )
    frame = frame.rename({c: c.strip() for c in frame.columns})
    if "R1" not in frame.columns:
        return None
    return (
        frame.select(
            pl.lit(station_id).alias("station_id"),
            pl.lit("dwd").alias("source"),
            pl.lit("DE").alias("country"),
            # polars wants hour and minute together; the feed is hour-resolution.
            (pl.col("MESS_DATUM").str.strip_chars() + "00")
            .str.to_datetime("%Y%m%d%H%M", time_zone="UTC")
            .alias("valid_time"),
            pl.col("R1").str.strip_chars().cast(pl.Float64, strict=False).alias("precip_mm"),
            pl.col("QN_8").str.strip_chars().alias("quality"),
        )
        .filter(
            pl.col("precip_mm").is_not_null(),
            pl.col("precip_mm") != DWD_MISSING,
            pl.col("valid_time") >= start,
            pl.col("valid_time") < end,
        )
    )


# --------------------------------------------------------------------------
# Météo-France
# --------------------------------------------------------------------------


def mf_department_urls() -> dict[str, str]:
    """Map département code to its 2025-2026 hourly archive URL."""
    raw = _get(
        f"https://www.data.gouv.fr/api/1/datasets/{MF_DATASET}/",
        "meteofrance/dataset.json",
        timeout=120,
    )
    if raw is None:
        raise RuntimeError("could not reach the data.gouv.fr dataset API")
    pattern = re.compile(rf"^HOR_departement_(\d{{2}}|2A|2B)_periode_{MF_PERIOD}$")
    urls = {}
    for resource in json.loads(raw)["resources"]:
        match = pattern.match(resource["title"])
        if match:
            urls[match.group(1)] = resource["url"]
    return urls


def mf_department(dep: str, url: str, start: datetime, end: datetime) -> pl.DataFrame | None:
    """Hourly totals for every station in one département."""
    raw = _get(url, f"meteofrance/{dep}.csv.gz", timeout=600)
    if raw is None:
        return None
    try:
        payload = gzip.decompress(raw)
    except (OSError, EOFError):
        return None

    frame = pl.read_csv(
        io.BytesIO(payload), separator=";", infer_schema_length=0, encoding="utf8-lossy"
    )
    if "RR1" not in frame.columns:
        return None
    return (
        frame.select(
            ("MF:" + pl.col("NUM_POSTE").str.strip_chars()).alias("station_id"),
            pl.lit("meteofrance").alias("source"),
            pl.lit("FR").alias("country"),
            pl.col("NOM_USUEL").str.strip_chars().alias("name"),
            pl.col("LAT").cast(pl.Float64, strict=False).alias("lat"),
            pl.col("LON").cast(pl.Float64, strict=False).alias("lon"),
            pl.col("ALTI").cast(pl.Float64, strict=False).alias("elevation_m"),
            (pl.col("AAAAMMJJHH").str.strip_chars() + "00")
            .str.to_datetime("%Y%m%d%H%M", time_zone="UTC")
            .alias("valid_time"),
            pl.col("RR1").cast(pl.Float64, strict=False).alias("precip_mm"),
            pl.col("QRR1").str.strip_chars().alias("quality"),
        )
        .filter(
            pl.col("precip_mm").is_not_null(),
            pl.col("valid_time") >= start,
            pl.col("valid_time") < end,
        )
    )


# --------------------------------------------------------------------------


def _run(label: str, jobs: list, fn, workers: int) -> list[pl.DataFrame]:
    """Map ``fn`` over ``jobs`` on a thread pool, reporting progress as it goes."""
    started = time.monotonic()
    frames: list[pl.DataFrame] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, frame in enumerate(pool.map(fn, jobs), start=1):
            if frame is not None and frame.height:
                frames.append(frame)
            if index % 100 == 0 or index == len(jobs):
                rate = index / max(time.monotonic() - started, 1e-6)
                print(
                    f"[{label}] {index}/{len(jobs)} "
                    f"({len(frames)} with data, {rate:.1f}/s)",
                    flush=True,
                )
    return frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--source", choices=["ghcnh", "dwd", "meteofrance"], action="append"
    )
    args = parser.parse_args()
    sources = args.source or ["ghcnh", "dwd", "meteofrance"]

    start, end = _window()
    print(f"track_a window: {start:%Y-%m-%d} .. {end:%Y-%m-%d}", flush=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    obs_frames: list[pl.DataFrame] = []
    station_frames: list[pl.DataFrame] = []

    if "ghcnh" in sources:
        stations = ghcnh_stations()
        print(
            f"[ghcnh] {stations.height} stations across "
            f"{', '.join(GHCNH_COUNTRIES)}",
            flush=True,
        )
        lookup = dict(zip(stations["station_id"], stations["country"]))
        frames = _run(
            "ghcnh",
            stations["station_id"].to_list(),
            lambda s: ghcnh_observations(s, lookup[s], start, end),
            args.workers,
        )
        if frames:
            obs = pl.concat(frames)
            obs_frames.append(obs)
            station_frames.append(
                stations.filter(
                    pl.col("station_id").is_in(obs["station_id"].unique().to_list())
                )
            )

    if "dwd" in sources:
        stations = dwd_stations(start, end)
        print(f"[dwd] {stations.height} stations span the window", flush=True)
        frames = _run(
            "dwd",
            stations["station_id"].to_list(),
            lambda s: dwd_observations(s, start, end),
            args.workers,
        )
        if frames:
            obs = pl.concat(frames)
            obs_frames.append(obs)
            # Keep only stations that actually returned observations.
            station_frames.append(
                stations.filter(
                    pl.col("station_id").is_in(obs["station_id"].unique().to_list())
                )
            )

    if "meteofrance" in sources:
        urls = mf_department_urls()
        print(f"[meteofrance] {len(urls)} départements for {MF_PERIOD}", flush=True)
        frames = _run(
            "meteofrance",
            sorted(urls.items()),
            lambda item: mf_department(item[0], item[1], start, end),
            min(args.workers, 10),
        )
        if frames:
            combined = pl.concat(frames)
            obs_frames.append(combined.select(OBS_SCHEMA))
            station_frames.append(
                combined.select(STATION_SCHEMA).unique(subset=["station_id"], keep="first")
            )

    if not obs_frames:
        print("no observations ingested")
        return

    observations = pl.concat([f.select(OBS_SCHEMA) for f in obs_frames])
    before = observations.height
    observations = (
        observations.filter(pl.col("precip_mm") <= MAX_HOURLY_MM)
        # A handful of GHCNh stations report the same timestamp twice when a
        # special observation lands alongside the routine one.
        .unique(subset=["station_id", "valid_time"], keep="first")
        .sort("station_id", "valid_time")
    )
    dropped = before - observations.height
    if dropped:
        print(
            f"dropped {dropped} row(s): above {MAX_HOURLY_MM:g} mm/h or duplicate "
            f"station-hour",
            flush=True,
        )

    inventory = pl.concat([f.select(STATION_SCHEMA) for f in station_frames]).sort("station_id")

    obs_path = DERIVED / "precip_obs_hourly.parquet"
    inv_path = DERIVED / "precip_obs_stations.parquet"
    observations.write_parquet(obs_path)
    inventory.write_parquet(inv_path)

    by_country = (
        observations.group_by("country")
        .agg(
            pl.col("station_id").n_unique().alias("stations"),
            pl.len().alias("rows"),
        )
        .sort("country")
    )
    status = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "sources": sources,
        "stations": inventory.height,
        "rows": observations.height,
        "dropped_above_max_hourly_mm": dropped,
        "by_country": by_country.to_dicts(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (DERIVED / "precip_obs_status.json").write_text(json.dumps(status, indent=2))

    print()
    print(by_country)
    print(f"wrote {obs_path} ({observations.height:,} rows)")
    print(f"wrote {inv_path} ({inventory.height:,} stations)")


if __name__ == "__main__":
    main()
