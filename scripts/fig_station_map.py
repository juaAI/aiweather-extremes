"""Europe-wide station network map: synoptic vs solar.

Fetches full catalogues:
  GET /v1/station-data/stations
  GET /v1/station-data/solar-stations

Plots every station in a Europe extent (same ~2.3k synoptic footprint as
the verification domain overview). Analysis-country borders are outlined
but stations outside that set (CH, BE, SE, …) stay visible.

Writes ``data/derived/station_locations.parquet`` and
``figures/fig1_station_network.png``.

Run:  uv run python scripts/fig_station_map.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.lines import Line2D
from shapely.geometry import box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qe_client import PROJECT_ROOT, QEClient
from style import COUNTRIES, apply_style

FIGURES = PROJECT_ROOT / "figures"
DERIVED = PROJECT_ROOT / "data" / "derived"
OUT_PARQUET = DERIVED / "station_locations.parquet"
OUT_FIG = FIGURES / "fig1_station_network.png"

# Clip Natural Earth overseas polygons; map extent is derived from analysis
# countries + a small pad (keeps the figure compact on the page).
MAINLAND = box(-25.0, 34.0, 45.0, 72.0)
PAD_DEG = 0.9

SYN_COLOR = "#1F4E79"  # deep blue — synoptic (wind / 2 m temp)
SOL_COLOR = "#E65C00"  # strong orange — solar radiation


def _analysis_outline():
    shp = shpreader.natural_earth(
        resolution="50m", category="cultural", name="admin_0_countries"
    )
    geoms = []
    for rec in shpreader.Reader(shp).records():
        iso = rec.attributes.get("ISO_A2_EH") or rec.attributes.get("ISO_A2")
        if iso in COUNTRIES:
            clipped = rec.geometry.intersection(MAINLAND)
            if not clipped.is_empty:
                geoms.append(clipped)
    return unary_union(geoms) if geoms else None


def _fetch_stations(client: QEClient, path: str) -> pl.DataFrame:
    data = client.request("GET", path)
    rows = data["stations"] if isinstance(data, dict) else data
    return pl.DataFrame(
        {
            "station": [r["station"] for r in rows],
            "name": [r.get("name") for r in rows],
            "latitude": [float(r["latitude"]) for r in rows],
            "longitude": [float(r["longitude"]) for r in rows],
            "elevation": [float(r.get("elevation") or 0.0) for r in rows],
        }
    )


def _extent_from_region(region) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = region.bounds
    # Cap the Arctic: Norway's northern tip leaves a tall empty frame.
    return (
        minx - PAD_DEG,
        maxx + PAD_DEG,
        miny - PAD_DEG,
        min(maxy + PAD_DEG, 64.5),
    )


def _in_extent(df: pl.DataFrame, extent: tuple[float, float, float, float]) -> pl.DataFrame:
    lo, hi, la0, la1 = extent
    return df.filter(
        (pl.col("longitude") >= lo)
        & (pl.col("longitude") <= hi)
        & (pl.col("latitude") >= la0)
        & (pl.col("latitude") <= la1)
    )


def load_or_fetch() -> pl.DataFrame:
    client = QEClient()
    analysis = _analysis_outline()
    extent = _extent_from_region(analysis)
    print("fetch synoptic stations …")
    syn = _in_extent(
        _fetch_stations(client, "/v1/station-data/stations"), extent
    ).with_columns(pl.lit("synoptic").alias("network"))
    print("fetch solar stations …")
    sol = _in_extent(
        _fetch_stations(client, "/v1/station-data/solar-stations"), extent
    ).with_columns(pl.lit("solar").alias("network"))
    print(f"  extent {tuple(round(x, 2) for x in extent)}")
    print(f"  synoptic in frame: {syn.height:,}")
    print(f"  solar in frame:    {sol.height:,}")
    out = pl.concat([syn, sol], how="diagonal_relaxed")
    DERIVED.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT_PARQUET)
    print("wrote", OUT_PARQUET)
    return out


def draw(df: pl.DataFrame) -> None:
    apply_style()
    syn = df.filter(pl.col("network") == "synoptic")
    sol = df.filter(pl.col("network") == "solar")
    analysis = _analysis_outline()
    extent = _extent_from_region(analysis)

    proj = ccrs.LambertConformal(central_longitude=8.0, central_latitude=50.0)
    fig = plt.figure(figsize=(4.8, 4.4))
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#D8DDE3", zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#EFECE6", zorder=1)
    ax.add_feature(
        cfeature.BORDERS.with_scale("50m"), lw=0.25, edgecolor="#FFFFFF", zorder=2
    )
    ax.add_feature(
        cfeature.COASTLINE.with_scale("50m"), lw=0.4, edgecolor="#8A8A8A", zorder=2
    )
    if analysis is not None:
        ax.add_geometries(
            [analysis],
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor="#4A4A4A",
            linewidth=0.7,
            zorder=3,
        )

    # Synoptic under; solar on top — white edges like the reference map.
    ax.scatter(
        syn["longitude"].to_numpy(),
        syn["latitude"].to_numpy(),
        s=5.5,
        c=SYN_COLOR,
        alpha=0.85,
        edgecolors="white",
        linewidths=0.15,
        transform=ccrs.PlateCarree(),
        zorder=4,
        rasterized=True,
    )
    ax.scatter(
        sol["longitude"].to_numpy(),
        sol["latitude"].to_numpy(),
        s=7,
        c=SOL_COLOR,
        alpha=0.9,
        edgecolors="white",
        linewidths=0.2,
        transform=ccrs.PlateCarree(),
        zorder=5,
        rasterized=True,
    )

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=SYN_COLOR,
            markeredgecolor="white",
            markersize=7,
            label=f"Synoptic: wind & 2 m temp  ({syn.height:,})",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=SOL_COLOR,
            markeredgecolor="white",
            markersize=7.5,
            label=f"Solar radiation  ({sol.height:,})",
        ),
    ]
    ax.legend(
        handles=handles,
        loc="lower left",
        frameon=True,
        fancybox=False,
        edgecolor="#CCCCCC",
        fontsize=7.5,
        borderpad=0.4,
        handletextpad=0.4,
    )
    for spine in ax.spines.values():
        spine.set_visible(False)

    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=240, bbox_inches="tight", pad_inches=0.04, facecolor="white")
    plt.close(fig)
    print(f"wrote {OUT_FIG} (synoptic={syn.height}, solar={sol.height})")
    return syn.height, sol.height


def main() -> None:
    try:
        df = load_or_fetch()
    except RuntimeError as exc:
        if OUT_PARQUET.exists():
            print(f"API unavailable ({exc}); using {OUT_PARQUET}")
            df = pl.read_parquet(OUT_PARQUET)
        else:
            raise
    n_syn, n_sol = draw(df)
    print(f"caption counts: synoptic={n_syn}, solar={n_sol}")


if __name__ == "__main__":
    main()
