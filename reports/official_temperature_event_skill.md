# Temperature skill on externally documented record-temperature events

Continental externally documented record-temperature episodes are evaluated over their affected station footprints and durations. Forecast samples are matched pairwise to IFS; ensembles are evaluated through their means and the paper's causal bias correction is applied.

Coverage differs by model and event; episode counts, pairwise-matched sample counts, and leave-one-event-out uncertainty are reported without a post hoc inclusion threshold.

## Pooled 6--48 h skill

| model | skill (%) | episode jackknife SE | episodes | samples |
|---|---:|---:|---:|---:|
| Jua EPT-2.1 Europa | +10.5 | 2.2 | 5 | 6,310 |
| Jua EPT-2 HRRR | -3.1 | 1.6 | 2 | 1,710 |
| Jua EPT-2 Reasoning | +13.5 | 8.7 | 2 | 109 |
| Jua EPT-2e | -14.2 | 5.1 | 5 | 445 |
| Microsoft Aurora | -0.6 | 25.8 | 2 | 690 |
| ECMWF AIFS | +11.8 | 41.0 | 3 | 208 |
| ECMWF AIFS ENS (mean) | -10.3 | 2.7 | 2 | 6,060 |
| ECMWF ENS (mean) | -4.9 | 2.7 | 5 | 9,777 |
| NOAA GFS | -8.0 | -- | 1 | 151 |
| DWD ICON Global | +6.0 | -- | 1 | 114 |

## Skill by episode (6--48 h)

| episode | Jua EPT-2.1 Europa | Jua EPT-2 HRRR | Jua EPT-2 Reasoning | Jua EPT-2e | Microsoft Aurora | ECMWF AIFS | ECMWF AIFS ENS (mean) | ECMWF ENS (mean) | NOAA GFS | DWD ICON Global |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| temp_apr2026 | +14.4 | -- | -- | +12.0 | -- | -- | -- | +0.5 | -- | -- |
| temp_dec2025 | +26.4 | -- | -- | -9.9 | -- | -- | -- | +1.0 | -- | -- |
| temp_feb2026 | -2.1 | -- | -- | -63.4 | -51.5 | -33.7 | -- | -2.9 | -- | -- |
| temp_jun2026 | +8.6 | -1.1 | -0.2 | -17.1 | +0.1 | +12.8 | -10.3 | -10.9 | -8.0 | +6.0 |
| temp_may2026 | +12.0 | -4.3 | +17.1 | -12.9 | -- | -60.6 | -15.7 | -6.3 | -- | -- |

## Event sample inventory

| episode | footprint station-hours before forecast matching | stations | countries |
|---|---:|---:|---:|
| temp_apr2026 | 7,952 | 497 | 2 |
| temp_dec2025 | 696 | 58 | 2 |
| temp_feb2026 | 6,996 | 583 | 4 |
| temp_jun2026 | 42,528 | 1329 | 10 |
| temp_may2026 | 19,880 | 497 | 2 |
