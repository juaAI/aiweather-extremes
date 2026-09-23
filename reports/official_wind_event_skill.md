# Wind skill on full-cohort common event samples

All models and IFS are evaluated on identical station, valid-time, initialisation, and lead samples. Leads are 6--48 h at 6-hourly intervals; forecasts use the paper's causal bias correction.

| model | skill (%) | event jackknife SE | events | samples |
|---|---:|---:|---:|---:|
| Jua EPT-2.1 Europa | +6.4 | 1.8 | 7 | 123,847 |
| Jua EPT-2 HRRR | +3.9 | 1.3 | 7 | 123,847 |
| Jua EPT-2 Reasoning | +3.3 | 0.5 | 7 | 123,847 |
| Jua EPT-2e | -0.3 | 0.8 | 7 | 123,847 |
| Microsoft Aurora | +0.7 | 0.9 | 7 | 123,847 |
| ECMWF AIFS | -6.0 | 1.3 | 7 | 123,847 |
| ECMWF AIFS ENS (mean) | -5.1 | 0.7 | 7 | 123,847 |
| ECMWF ENS (mean) | +1.7 | 0.7 | 7 | 123,847 |
| NOAA GFS | -12.6 | 1.8 | 7 | 123,847 |
| DWD ICON Global | +2.4 | 2.2 | 7 | 123,847 |

## Skill by event

| event | Jua EPT-2.1 Europa | Jua EPT-2 HRRR | Jua EPT-2 Reasoning | Jua EPT-2e | Microsoft Aurora | ECMWF AIFS | ECMWF AIFS ENS (mean) | ECMWF ENS (mean) | NOAA GFS | DWD ICON Global |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Storm Amy | +6.8 | +2.9 | +2.2 | -1.5 | -0.9 | -7.5 | -5.8 | +0.3 | -15.2 | +3.4 |
| Storm Benjamin | +6.8 | +1.5 | +3.5 | +1.2 | +2.9 | -3.5 | -4.8 | +2.0 | -15.0 | +0.9 |
| Storm Deborah | +13.7 | +9.7 | +2.5 | -1.7 | +1.5 | -10.3 | -7.2 | +0.6 | -5.1 | +11.8 |
| Storm Goretti | +5.0 | +4.6 | +5.5 | +2.7 | +2.1 | -1.3 | -1.6 | +3.3 | -16.4 | +0.4 |
| Storm Marlis | +2.7 | +3.0 | +4.1 | +1.9 | +5.5 | -4.8 | -0.7 | +2.3 | -8.5 | -2.1 |
| Storm Nils | +1.8 | +2.3 | +3.5 | -1.6 | -1.3 | -6.5 | -6.0 | +2.8 | -11.1 | -2.5 |
| North Sea autumn storm | +6.2 | +16.5 | +8.4 | +14.8 | +13.0 | +13.1 | +8.8 | +8.4 | -9.2 | +2.5 |
