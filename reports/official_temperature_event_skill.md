# Temperature skill on full-cohort common event samples

All models and IFS are evaluated on identical station, valid-time, initialisation, and lead samples. Leads are 6--48 h at 6-hourly intervals; forecasts use the paper's causal bias correction.

| model | skill (%) | event jackknife SE | events | samples |
|---|---:|---:|---:|---:|
| Jua EPT-2.1 Europa | +15.4 | 1.6 | 5 | 231,065 |
| Jua EPT-2 HRRR | +12.3 | 2.7 | 5 | 231,065 |
| Jua EPT-2 Reasoning | +6.5 | 0.6 | 5 | 231,065 |
| Jua EPT-2e | +4.3 | 1.1 | 5 | 231,065 |
| Microsoft Aurora | +2.5 | 0.9 | 5 | 231,065 |
| ECMWF AIFS | -3.4 | 3.9 | 5 | 231,065 |
| ECMWF AIFS ENS (mean) | +0.1 | 2.0 | 5 | 231,065 |
| ECMWF ENS (mean) | -0.9 | 0.1 | 5 | 231,065 |
| NOAA GFS | -25.4 | 7.5 | 5 | 231,065 |
| DWD ICON Global | +9.8 | 2.3 | 5 | 231,065 |

## Skill by event

| event | Jua EPT-2.1 Europa | Jua EPT-2 HRRR | Jua EPT-2 Reasoning | Jua EPT-2e | Microsoft Aurora | ECMWF AIFS | ECMWF AIFS ENS (mean) | ECMWF ENS (mean) | NOAA GFS | DWD ICON Global |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Early-April record warm spell | +22.8 | +21.1 | +8.1 | +9.1 | +3.8 | +8.6 | +7.9 | -0.8 | -16.9 | +19.6 |
| Central European December record warmth | +14.5 | +22.2 | +8.7 | +7.9 | +9.9 | +6.3 | +7.7 | -4.8 | -24.0 | +7.6 |
| Late-February European record warmth | +8.0 | +5.5 | +1.9 | -1.9 | -4.5 | +0.1 | -0.9 | -0.3 | -23.5 | +6.5 |
| Late-June European record heatwave | +15.1 | +9.2 | +6.6 | +4.5 | +2.7 | -3.3 | -0.2 | -0.8 | -35.9 | +9.1 |
| Western European May heatwave | +14.4 | +13.8 | +7.0 | +3.6 | +3.8 | -11.5 | -3.4 | -1.1 | -16.7 | +6.5 |
