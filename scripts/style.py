"""Shared plotting style for all paper figures. Import from here; do not
redefine colors or labels in figure modules."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

WIND = "wind_speed_at_height_level_10m"
TEMP = "air_temperature_at_height_level_2m"
SOLAR = "surface_downwelling_shortwave_flux_sum_1h"
PRECIP = "precipitation_amount_sum_1h"
VAR_TITLE = {
    WIND: "10 m wind speed",
    TEMP: "2 m temperature",
    SOLAR: "1 h shortwave accumulation",
    PRECIP: "1 h precipitation",
}
# Solar figures convert J/m2 -> Wh/m2 (divide by 3600) before plotting.
VAR_UNIT = {WIND: "m/s", TEMP: "\u00b0C", SOLAR: "Wh/m\u00b2", PRECIP: "mm"}
VAR_SHORT = {WIND: "wind", TEMP: "temp", SOLAR: "solar", PRECIP: "precip"}

# Precipitation uses wet-hour climatological regimes (dry mass + ERA5 1991-2020
# wet-hour percentile bands), not the symmetric lt_q5..gt_q95 of the other
# variables. Kept separate so the shared BUCKET_ORDER stays untouched.
PRECIP_BUCKET_ORDER = ["all", "dry", "wet_lt_p50", "p50_p75", "p75_p95", "gt_p95"]
PRECIP_BUCKET_LABELS = {
    "all": "All conditions",
    "dry": "Dry (<0.1 mm)",
    "wet_lt_p50": "Light (wet <P50)",
    "p50_p75": "Moderate (P50\u201375)",
    "p75_p95": "High (P75\u201395)",
    "gt_p95": "Heavy (>P95)",
}
PRECIP_BUCKET_SHORT = {
    "all": "all",
    "dry": "dry",
    "wet_lt_p50": "<P50",
    "p50_p75": "P50\u201375",
    "p75_p95": "P75\u201395",
    "gt_p95": ">P95",
}
PRECIP_BUCKET_TEX = {
    "all": "All",
    "dry": "Dry",
    "wet_lt_p50": "$<$P50",
    "p50_p75": "P50--75",
    "p75_p95": "P75--95",
    "gt_p95": "$>$P95",
}

REFERENCE = "ecmwf_ifs_single"

BUCKET_ORDER = ["all", "lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]
BUCKET_LABELS = {
    "all": "All conditions",
    "lt_q5": "Very low (<P5)",
    "q5_q25": "Low (P5\u201325)",
    "q25_q75": "Typical (P25\u201375)",
    "q75_q95": "High (P75\u201395)",
    "gt_q95": "Very high (>P95)",
}

DISPLAY = {
    "ept2_1_helios": "Jua EPT-2.1 Helios",
    "ept2_1_europa": "Jua EPT-2.1 Europa",
    "ept2_hrrr": "Jua EPT-2 HRRR",
    "ept2_e": "Jua EPT-2e",
    "ept2_reasoning": "Jua EPT-2 Reasoning",
    "aifs": "ECMWF AIFS",
    "aurora": "Microsoft Aurora",
    "ecmwf_ifs_single": "ECMWF IFS",
    "noaa_gfs_single": "NOAA GFS",
    "icon_global": "DWD ICON Global",
    "icon_eu": "DWD ICON-EU",
    "ecmwf_ens": "ECMWF ENS (mean)",
}

# Model identity is encoded on TWO channels: color AND line style, so no two
# co-plotted models share both. Line style carries paradigm (solid =
# generative ensemble, dash-dot = regression AI, dashed = physics, black
# solid = reference), which makes the paradigm structure readable directly
# from any line chart and disambiguates near hues (e.g. HRRR cyan, solid, vs
# AIFS blue, dash-dot).
COLORS = {
    "ept2_1_europa": "#009E73",  # green
    "ept2_hrrr": "#17BECF",  # cyan
    "ept2_reasoning": "#D62728",  # red
    "ept2_e": "#7A3EB1",  # violet
    "ept2_1_helios": "#E69F00",  # amber
    "aurora": "#FF7F0E",  # orange
    "aifs": "#1F4E9C",  # deep blue
    "ecmwf_ifs_single": "#000000",  # black (reference)
    "ecmwf_ens": "#56B4E9",  # light blue
    "noaa_gfs_single": "#7F7F7F",  # grey
    "icon_global": "#8C510A",  # brown
    "icon_eu": "#BCBD22",  # olive
}

LINESTYLES = {
    # generative ensembles: solid
    "ept2_1_europa": "-",
    "ept2_hrrr": "-",
    "ept2_1_helios": "-",
    # Regression AI: a long dash-dot cycle that remains legible in compact
    # legends. Matplotlib's default '-.' collapses visually at paper scale.
    "ept2_reasoning": (0, (5.0, 1.5, 1.2, 1.5)),
    "ept2_e": (0, (5.0, 1.5, 1.2, 1.5)),
    "aurora": (0, (5.0, 1.5, 1.2, 1.5)),
    "aifs": (0, (5.0, 1.5, 1.2, 1.5)),
    # Physics: long dashed (reference stays solid black).
    "ecmwf_ifs_single": "-",
    "ecmwf_ens": (0, (6.0, 2.0)),
    "noaa_gfs_single": (0, (6.0, 2.0)),
    "icon_global": (0, (6.0, 2.0)),
    "icon_eu": (0, (6.0, 2.0)),
}

# Marker is a third, model-specific identity channel. This is deliberately
# redundant with colour and line style so models remain distinguishable in
# grayscale, for colour-vision deficiencies, and in compact PDF legends.
MARKERS = {
    "ept2_1_helios": "*",
    "ept2_1_europa": "o",
    "ept2_hrrr": "s",
    "ept2_reasoning": "D",
    "ept2_e": "P",
    "aurora": "v",
    "aifs": "X",
    "ecmwf_ens": "^",
    "noaa_gfs_single": "h",
    "icon_global": "<",
    "icon_eu": ">",
    "ecmwf_ifs_single": "o",
}

# Europe country set for all extracts and figures. SE dropped (noisy solar /
# thin station coverage that dominated sample-weighted aggregates).
# CH and BE included: both have synoptic + solar benchmarks in the store.
COUNTRIES = [
    "DE",
    "FR",
    "GB",
    "ES",
    "IT",
    "PL",
    "NL",
    "BE",
    "CH",
    "NO",
    "AT",
    "CZ",
    "DK",
]

# Order used for legends and bar/heatmap rows (reference last).
MODEL_ORDER = [
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "ept2_e",
    "aurora",
    "aifs",
    "ecmwf_ens",
    "noaa_gfs_single",
    "icon_global",
    "icon_eu",
    "ecmwf_ifs_single",
]

# Canonical order for every line-chart legend. Filtering this list to the
# plotted models keeps a model in the same relative position in every figure.
LINE_MODEL_ORDER = ["ept2_1_helios", *MODEL_ORDER]


def ordered_line_models(models: list[str]) -> list[str]:
    available = set(models)
    ordered = [m for m in LINE_MODEL_ORDER if m in available]
    return ordered + sorted(available.difference(ordered))


def model_legend_handles(models: list[str], ncol: int | None = None) -> list[Line2D]:
    """Canonical, fully styled handles, optionally arranged row-major.

    Matplotlib fills multi-column legends down columns. Reordering here makes
    the visible rows follow ``LINE_MODEL_ORDER`` in every figure.
    """
    handles = [
        Line2D(
            [0],
            [0],
            color=COLORS.get(model, "gray"),
            linestyle=LINESTYLES.get(model, "-"),
            marker=MARKERS.get(model, "o"),
            linewidth=2.2,
            markersize=5.0,
            label=DISPLAY.get(model, model),
        )
        for model in ordered_line_models(models)
    ]
    if not ncol or ncol <= 1:
        return handles
    nrows = (len(handles) + ncol - 1) // ncol
    return [
        handles[row * ncol + col]
        for col in range(ncol)
        for row in range(nrows)
        if row * ncol + col < len(handles)
    ]

# Generative regionals (Track B comparison set; ICON-EU added there).
REGIONAL_MODELS = ["ept2_1_europa", "ept2_hrrr"]


# Always pass this to fig.savefig — rcParams alone is easy to miss when
# calling figure helpers outside main().
SAVE_DPI = 250


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 200,
            "savefig.dpi": SAVE_DPI,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "font.size": 10,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9.5,
            "legend.frameon": False,
            "figure.facecolor": "white",
        }
    )
