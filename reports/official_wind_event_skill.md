# 10 m wind skill on externally documented European windstorms

Continental externally documented windstorm episodes are evaluated over their affected station footprints and durations. Forecast samples are matched pairwise to IFS; ensembles are evaluated through their means and the paper's causal bias correction is applied.

Coverage differs by model and event; episode counts, pairwise-matched sample counts, and leave-one-event-out uncertainty are reported without a post hoc inclusion threshold.

## Pooled 6--48 h skill

| model | skill (%) | episode jackknife SE | episodes | samples |
|---|---:|---:|---:|---:|
| Jua EPT-2.1 Europa | +0.5 | 4.5 | 5 | 2,596 |
| Jua EPT-2 HRRR | -4.3 | 3.0 | 5 | 2,035 |
| Jua EPT-2 Reasoning | +6.6 | 3.0 | 4 | 244 |
| Jua EPT-2e | -3.7 | 5.6 | 5 | 1,678 |
| Microsoft Aurora | -0.7 | -- | 1 | 698 |
| ECMWF AIFS | -1.7 | 43.0 | 3 | 1,011 |
| ECMWF AIFS ENS (mean) | +2.3 | 5.2 | 4 | 421 |
| ECMWF ENS (mean) | -0.5 | 0.7 | 6 | 4,649 |
| NOAA GFS | -79.5 | -- | 1 | 7 |
| DWD ICON Global | +3.5 | -- | 1 | 18 |

## Skill by episode (6--48 h)

| episode | Jua EPT-2.1 Europa | Jua EPT-2 HRRR | Jua EPT-2 Reasoning | Jua EPT-2e | Microsoft Aurora | ECMWF AIFS | ECMWF AIFS ENS (mean) | ECMWF ENS (mean) | NOAA GFS | DWD ICON Global |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| wind_amy2025 | +4.8 | -9.5 | +18.4 | -14.8 | -- | -- | -- | -0.3 | -- | +3.5 |
| wind_benjamin2025 | +19.2 | -1.1 | +4.6 | +24.2 | -- | -62.3 | -30.3 | +0.6 | -- | -- |
| wind_deborah2026 | -8.5 | +30.0 | +11.6 | -1.2 | -- | -72.0 | -- | -11.8 | -- | -- |
| wind_goretti2026 | -- | -- | -- | -- | -0.7 | +2.1 | +0.3 | -4.1 | -- | -- |
| wind_marlis2026 | +3.7 | -15.5 | +1.1 | -0.8 | -- | -- | -- | -4.7 | -- | -- |
| wind_nils2026 | -2.3 | -4.7 | -- | -11.1 | -- | -- | -248.9 | -2.1 | -79.5 | -- |
| wind_sep2025 | -- | -- | -- | -- | -- | -- | +12.5 | -- | -- | -- |

## Event sample inventory

| episode | footprint station-hours before forecast matching | stations | countries |
|---|---:|---:|---:|
| wind_amy2025 | 9,276 | 773 | 7 |
| wind_benjamin2025 | 5,248 | 656 | 4 |
| wind_deborah2026 | 4,640 | 580 | 2 |
| wind_goretti2026 | 5,216 | 652 | 4 |
| wind_marlis2026 | 1,760 | 220 | 2 |
| wind_nils2026 | 5,568 | 464 | 2 |
| wind_sep2025 | 376 | 47 | 1 |
