# Do AI weather models lose skill in the tails?

ICLR 2027 submission materials for a station-based comparison of global and
regional weather forecast systems.

The main study verifies 10 m wind and 2 m temperature forecasts against 667
European stations from September 2025 through June 2026. Track A compares ten
alternatives with ECMWF IFS over 6–48 h. Observed-value regimes use fixed
ERA5 1991–2020 thresholds for each station, calendar day, and UTC hour.
A separate solar comparison adds EPT-2.1 Helios on hourly leads; its
regime-stratified results use 543 stations with fixed thresholds.
All reported results are out of sample with respect to model development.

## Main result

After a common causal domain-mean bias correction:

- every tested global learned system loses 2.7–6.8 points of relative MAE skill
  from all conditions to the >P95 regime in both variables;
- the ECMWF ENS mean shows the same direction;
- two regional generative systems and deterministic global numerical models
  do not show this penalty;
- without correction, four of five global learned systems retain the
  temperature penalty, while several wind rankings change;
- forecast-conditioned high-temperature-tail bias is within 0.3 °C of zero
  for every system, showing that the common sign of observation-conditioned
  bias is primarily a consequence of conditioning on the observation.
- Helios leads both solar tails but loses skill in the central irradiance
  regime, so specialization redistributes rather than uniformly improves
  skill.

The grouping holds under fixed climatological regimes and weakens under
in-window percentiles. The paper does not attribute it causally to
architecture, resolution, training objective, or domain.

## Submission artifacts

- `paper/main.pdf` — anonymous ICLR review PDF
- `paper/main.tex` — main manuscript
- `paper/supplement.tex` — appendix in the same PDF
- `paper/openreview_abstract.txt` — abstract for OpenReview
- `overleaf_package.zip` — self-contained LaTeX upload
- `SUBMISSION_CHECKLIST.md` — desk-rejection and author-side checks

## Rebuild

Install dependencies and regenerate all score-based tables and figures from
the committed compact aggregates:

```bash
uv sync --frozen
uv run python scripts/prepare_climatology_figure_data.py
EXTREMES_VARIANT=_climatology uv run python scripts/make_numbers.py
EXTREMES_VARIANT=_climatology uv run python scripts/write_paper_tables.py
EXTREMES_VARIANT=_climatology uv run python scripts/figures_v4.py
EXTREMES_VARIANT=_climatology uv run python scripts/fig_tail_penalty.py
uv run python scripts/fig_conditional_bias.py
uv run python scripts/build_paper.py
uv run python scripts/validate_submission.py
uv run python scripts/package_overleaf.py
uv run python scripts/package_anonymous_code.py
```

The station map and station-count table are static products because station
identities and the 208 MB threshold file are not released. Precipitation is
not part of the ICLR submission's scientific claims; its unchanged aggregate
rows are stored explicitly in `data/derived/precip_aggregates_compact.parquet`
so re-aggregation never depends on an overwritten output file.

## Full extraction

The compact aggregates are committed so the paper rebuilds offline. Recreating
synoptic aggregates from station-level errors requires read-only access to the
verification warehouse:

```bash
uv run python scripts/extract_climatology_thresholds.py
uv run python scripts/extract_climatology_metrics.py
uv run python scripts/extract_forecast_conditioned_bias.py
uv run python scripts/aggregates.py --variant climatology
uv run python scripts/aggregates.py --variant window_matched
```

The extraction scripts require `CH_HOST`, `CH_PORT`, `CH_USER`, and
`CH_PASSWORD`. They jointly match model dates, assign fixed climatological
regimes, and archive intermediate cells under `data/cache/`.

## Validation

The final checks cover:

- official ICLR 2027 style and anonymous review mode;
- main-text page limit and bibliography/appendix order;
- numerical claims against the aggregate parquet;
- reproducible PDF compilation with Tectonic 0.16.9;
- self-contained source packaging;
- documented model/view omissions in the optional web export.

The manuscript evaluates ensemble means as point forecasts. It does not claim
to measure probabilistic calibration, spread, or reliability of the full
ensemble distribution.
