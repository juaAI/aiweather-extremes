# Inline paper numbers

Single source: `data/derived/final_aggregates_climatology.parquet` (72472 rows, aggregation self-test: PASS). Regenerate this report with `EXTREMES_VARIANT=_climatology python scripts/make_numbers.py` after aggregation.

Conventions: skill_pct = 100*(1 - MAE_model/MAE_IFS) (MAE primary; RMSE-based skill in kind=skill_pct_rmse), sample-matched per (country, lead) cell vs ECMWF IFS; cross-country and cross-lead pooling sample-weighted (RMSE quadratic, bias/MAE/CRPS linear); regime cells with <100 samples excluded; extremes = fixed ERA5 1991-2020 station/day/hour climatological regimes (obs_bucket); (±x.x) = jackknife SE over monthly replicates. All skills/biases/deltas signed, 1 decimal.

## Coverage omissions (models lacking leads are omitted, not interpolated)

- track_a h1_48: omitted (native cadence/horizon does not cover this grid): ECMWF AIFS, ECMWF AIFS ENS (mean), Microsoft Aurora, ECMWF ENS (mean)
- track_a h1_12 1 h shortwave accumulation: Jua EPT-2.1 Europa pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_12 1 h shortwave accumulation: Jua EPT-2.1 Helios pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_12 1 h shortwave accumulation: Jua EPT-2e pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_12 1 h shortwave accumulation: Jua EPT-2 HRRR pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_12 1 h shortwave accumulation: Jua EPT-2 Reasoning pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_12 1 h shortwave accumulation: DWD ICON Global pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_12 1 h shortwave accumulation: NOAA GFS pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: Jua EPT-2.1 Europa pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: Jua EPT-2.1 Helios pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: Jua EPT-2e pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: Jua EPT-2 HRRR pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: Jua EPT-2 Reasoning pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: DWD ICON Global pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_a h1_48 1 h shortwave accumulation: NOAA GFS pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_b h1_48: omitted (native cadence/horizon does not cover this grid): ECMWF ENS (mean)
- track_b h1_12 1 h shortwave accumulation: Jua EPT-2.1 Europa pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_b h1_12 1 h shortwave accumulation: Jua EPT-2.1 Helios pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_b h1_12 1 h shortwave accumulation: Jua EPT-2 HRRR pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_b h1_12 1 h shortwave accumulation: DWD ICON-EU pools 2/12 grid leads (missing leads omitted, never interpolated)
- track_b h1_48 1 h shortwave accumulation: Jua EPT-2.1 Europa pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_b h1_48 1 h shortwave accumulation: Jua EPT-2.1 Helios pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_b h1_48 1 h shortwave accumulation: Jua EPT-2 HRRR pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_b h1_48 1 h shortwave accumulation: DWD ICON-EU pools 8/48 grid leads (missing leads omitted, never interpolated)
- track_c solar: GB, IT, PL returned no benchmark rows at all (no solar station obs in QE for these countries) -> 9 of 12 countries. ES solar obs stop after March (421 samples in the whole window; most regime cells fall under the 100-sample floor); SE obs stop after April (no May/June monthly replicates).
- track_c solar tail regimes (lt_q5/q75_q95/gt_q95) exist only at daylight-valid leads: leads 6 h (valid 06/18 UTC) have no high-irradiance buckets, lead 12 h (valid 00/12 UTC) has no lt_q5 cell >=100 samples. Night leads drop out of tail pooling.

# Track A (10 m wind speed), skill_pct vs IFS, debiased

## 10 m wind speed — lead 6 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +7.6 | -6.2 | +5.3 | +11.6 | +7.6 | +7.8 |
| Jua EPT-2 HRRR | +3.3 | -0.0 | -0.6 | +4.3 | +3.7 | +5.0 |
| Jua EPT-2 Reasoning | +1.9 | -1.0 | +1.8 | +3.9 | +2.9 | -0.8 |
| Jua EPT-2e | -1.3 | -12.6 | -2.0 | +5.4 | +0.3 | -8.4 |
| Microsoft Aurora | -1.7 | -8.2 | -4.6 | +1.1 | +1.1 | -4.2 |
| ECMWF AIFS ENS (mean) | -3.7 | -11.2 | -5.0 | +0.9 | -1.9 | -8.6 |
| ECMWF AIFS | -6.8 | -12.0 | -9.6 | -3.4 | -3.1 | -11.5 |
| ECMWF ENS (mean) | +0.2 | -0.8 | -0.2 | +1.0 | +1.1 | -1.1 |
| NOAA GFS | -11.2 | +2.9 | -9.0 | -21.5 | -15.5 | +1.2 |
| DWD ICON Global | +4.6 | -5.3 | +3.2 | +4.3 | +4.2 | +9.7 |

## 10 m wind speed — lead 12 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +8.0 | -3.1 | +6.1 | +11.0 | +8.3 | +8.4 |
| Jua EPT-2 HRRR | +3.8 | +1.5 | +0.3 | +4.3 | +4.3 | +5.7 |
| Jua EPT-2 Reasoning | +2.3 | -1.1 | +2.1 | +4.6 | +3.6 | -0.9 |
| Jua EPT-2e | -1.1 | -11.5 | -2.5 | +5.1 | +1.5 | -7.9 |
| Microsoft Aurora | -1.7 | -7.7 | -4.8 | +0.7 | +1.5 | -3.8 |
| ECMWF AIFS ENS (mean) | -3.5 | -12.2 | -4.7 | +1.4 | -1.2 | -9.0 |
| ECMWF AIFS | -6.9 | -11.4 | -9.5 | -3.7 | -2.6 | -11.8 |
| ECMWF ENS (mean) | +0.5 | -0.7 | +0.3 | +1.5 | +1.3 | -1.1 |
| NOAA GFS | -11.3 | +3.5 | -8.5 | -22.1 | -15.7 | +1.0 |
| DWD ICON Global | +4.6 | -3.7 | +3.7 | +3.8 | +4.0 | +9.7 |

## 10 m wind speed — lead 24 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +7.7 | -1.9 | +6.0 | +10.6 | +7.4 | +8.2 |
| Jua EPT-2 HRRR | +4.5 | +2.6 | +1.0 | +5.2 | +4.8 | +6.1 |
| Jua EPT-2 Reasoning | +2.9 | -0.7 | +2.7 | +5.5 | +4.4 | -1.0 |
| Jua EPT-2e | -0.3 | -8.8 | -1.6 | +5.3 | +2.6 | -7.1 |
| Microsoft Aurora | -1.1 | -6.6 | -4.1 | +1.6 | +2.2 | -3.7 |
| ECMWF AIFS ENS (mean) | -2.8 | -12.1 | -3.7 | +3.0 | -0.6 | -9.4 |
| ECMWF AIFS | -6.0 | -9.7 | -8.1 | -2.6 | -2.1 | -11.9 |
| ECMWF ENS (mean) | +1.1 | -0.2 | +1.4 | +2.5 | +1.7 | -1.1 |
| NOAA GFS | -12.0 | +3.1 | -9.0 | -22.1 | -16.9 | -0.1 |
| DWD ICON Global | +4.0 | -3.2 | +3.2 | +3.3 | +2.8 | +9.2 |

## 10 m wind speed — lead 48 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +7.3 | -1.6 | +5.3 | +9.9 | +7.2 | +8.0 |
| Jua EPT-2 HRRR | +5.0 | +3.9 | +1.9 | +5.1 | +5.5 | +6.9 |
| Jua EPT-2 Reasoning | +3.9 | -0.2 | +3.9 | +6.8 | +5.7 | -0.6 |
| Jua EPT-2e | +1.0 | -6.6 | -0.0 | +6.0 | +4.3 | -5.9 |
| Microsoft Aurora | +0.3 | -5.6 | -3.0 | +3.1 | +4.1 | -3.0 |
| ECMWF AIFS ENS (mean) | -0.8 | -12.7 | -2.0 | +6.6 | +1.8 | -8.9 |
| ECMWF AIFS | -4.2 | -7.6 | -6.0 | -0.8 | -0.1 | -10.3 |
| ECMWF ENS (mean) | +2.3 | -1.4 | +3.1 | +5.2 | +2.7 | -1.7 |
| NOAA GFS | -12.4 | +1.3 | -9.7 | -21.8 | -17.1 | -1.2 |
| DWD ICON Global | +2.5 | -3.7 | +2.0 | +1.2 | +0.9 | +8.2 |

## 10 m wind speed — full horizon 6-48 h (6-hourly grid)

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +7.6 (±0.5) | -2.6 (±1.4) | +5.9 (±1.0) | +10.6 (±0.7) | +7.6 (±0.5) | +8.1 (±1.2) |
| Jua EPT-2 HRRR | +4.4 (±0.4) | +2.3 (±1.1) | +0.9 (±1.0) | +5.0 (±0.3) | +4.9 (±0.9) | +6.2 (±1.0) |
| Jua EPT-2 Reasoning | +2.9 (±0.1) | -0.6 (±0.4) | +2.8 (±0.5) | +5.5 (±0.3) | +4.5 (±0.3) | -0.8 (±0.4) |
| Jua EPT-2e | -0.2 (±0.2) | -9.1 (±0.9) | -1.4 (±1.1) | +5.5 (±0.5) | +2.7 (±0.6) | -6.9 (±0.6) |
| Microsoft Aurora | -0.9 (±0.3) | -6.8 (±1.1) | -4.0 (±1.1) | +1.8 (±0.8) | +2.6 (±0.7) | -3.5 (±0.6) |
| ECMWF AIFS ENS (mean) | -2.4 (±0.5) | -12.2 (±1.1) | -3.6 (±1.4) | +3.6 (±0.7) | -0.1 (±0.7) | -9.1 (±0.8) |
| ECMWF AIFS | -5.7 (±0.4) | -9.7 (±1.1) | -7.9 (±1.2) | -2.3 (±0.6) | -1.7 (±0.8) | -11.3 (±0.7) |
| ECMWF ENS (mean) | +1.3 (±0.2) | -0.7 (±0.7) | +1.5 (±0.6) | +3.0 (±0.4) | +1.9 (±0.4) | -1.2 (±0.2) |
| NOAA GFS | -11.9 (±0.7) | +2.7 (±1.5) | -9.1 (±1.4) | -21.9 (±1.5) | -16.6 (±1.3) | -0.1 (±0.8) |
| DWD ICON Global | +3.7 (±0.4) | -3.8 (±1.2) | +2.9 (±0.9) | +2.8 (±0.8) | +2.5 (±0.6) | +9.1 (±1.2) |

## 10 m wind speed — full horizon 6-240 h (6-hourly grid)

_(no data for track_a h6_240)_

## 10 m wind speed — full horizon 1-48 h (hourly grid)

_(no data for track_a h1_48)_

# Track A (2 m temperature), skill_pct vs IFS, debiased

## 2 m temperature — lead 6 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +8.3 | +3.0 | +7.1 | +7.5 | +8.3 | +12.7 |
| Jua EPT-2 HRRR | +10.1 | +8.7 | +8.4 | +6.3 | +10.0 | +19.6 |
| Jua EPT-2 Reasoning | +2.2 | -4.6 | +0.9 | +4.1 | +3.9 | -0.5 |
| Jua EPT-2e | -4.1 | -26.5 | -11.0 | +1.3 | +2.4 | -10.0 |
| Microsoft Aurora | -4.5 | -20.9 | -9.7 | -0.8 | -0.1 | -7.7 |
| ECMWF AIFS ENS (mean) | -4.0 | -23.8 | -6.8 | +0.2 | +1.2 | -10.2 |
| ECMWF AIFS | -4.5 | -25.9 | -7.8 | -1.3 | +0.9 | -7.6 |
| ECMWF ENS (mean) | -2.9 | -11.1 | -4.4 | -0.2 | -0.9 | -6.8 |
| NOAA GFS | -27.4 | -28.6 | -33.5 | -30.6 | -19.9 | -24.6 |
| DWD ICON Global | +5.3 | -4.1 | +2.0 | +4.2 | +7.8 | +10.2 |

## 2 m temperature — lead 12 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +12.0 | +6.2 | +11.3 | +11.1 | +12.1 | +16.0 |
| Jua EPT-2 HRRR | +12.6 | +10.1 | +11.1 | +9.3 | +12.6 | +21.4 |
| Jua EPT-2 Reasoning | +3.5 | -5.4 | +1.7 | +5.9 | +5.7 | +0.2 |
| Jua EPT-2e | -1.5 | -24.1 | -7.8 | +3.8 | +5.0 | -7.5 |
| Microsoft Aurora | -2.2 | -20.3 | -7.5 | +2.5 | +2.5 | -7.0 |
| ECMWF AIFS ENS (mean) | -1.0 | -22.2 | -3.9 | +3.1 | +4.3 | -6.6 |
| ECMWF AIFS | -2.4 | -25.1 | -6.0 | +0.9 | +3.1 | -5.3 |
| ECMWF ENS (mean) | -2.5 | -10.2 | -3.9 | +0.0 | -0.6 | -6.3 |
| NOAA GFS | -24.3 | -24.6 | -29.0 | -27.3 | -17.3 | -22.7 |
| DWD ICON Global | +7.0 | -3.0 | +3.9 | +5.9 | +9.8 | +11.7 |

## 2 m temperature — lead 24 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +11.5 | +5.8 | +11.0 | +10.6 | +12.1 | +14.7 |
| Jua EPT-2 HRRR | +12.1 | +10.3 | +11.8 | +9.3 | +11.7 | +19.5 |
| Jua EPT-2 Reasoning | +4.5 | -6.1 | +2.6 | +7.3 | +6.9 | +0.9 |
| Jua EPT-2e | +1.2 | -21.2 | -4.2 | +6.0 | +7.6 | -4.8 |
| Microsoft Aurora | -1.1 | -20.2 | -6.7 | +4.0 | +4.0 | -7.0 |
| ECMWF AIFS ENS (mean) | +0.3 | -21.4 | -2.7 | +4.0 | +6.3 | -4.9 |
| ECMWF AIFS | -1.6 | -24.2 | -5.0 | +1.4 | +4.5 | -5.1 |
| ECMWF ENS (mean) | -1.8 | -9.9 | -3.4 | +0.9 | +0.1 | -6.1 |
| NOAA GFS | -24.3 | -23.5 | -26.4 | -27.5 | -18.3 | -23.3 |
| DWD ICON Global | +6.2 | -3.9 | +4.3 | +4.7 | +9.3 | +10.3 |

## 2 m temperature — lead 48 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +11.7 | +6.1 | +11.2 | +11.3 | +11.6 | +14.6 |
| Jua EPT-2 HRRR | +12.3 | +11.6 | +12.3 | +10.2 | +11.0 | +18.5 |
| Jua EPT-2 Reasoning | +6.1 | -5.9 | +3.6 | +9.2 | +8.7 | +2.3 |
| Jua EPT-2e | +3.2 | -18.9 | -2.1 | +8.1 | +9.3 | -2.8 |
| Microsoft Aurora | +0.3 | -19.4 | -5.7 | +6.2 | +5.3 | -6.7 |
| ECMWF AIFS ENS (mean) | +2.5 | -20.6 | -0.7 | +6.7 | +8.1 | -3.3 |
| ECMWF AIFS | +0.4 | -22.5 | -3.2 | +3.8 | +6.6 | -3.8 |
| ECMWF ENS (mean) | -0.5 | -9.4 | -2.2 | +2.9 | +1.2 | -5.7 |
| NOAA GFS | -22.4 | -19.2 | -22.0 | -25.2 | -18.4 | -22.8 |
| DWD ICON Global | +4.1 | -3.6 | +2.4 | +2.3 | +6.4 | +8.8 |

## 2 m temperature — full horizon 6-48 h (6-hourly grid)

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +11.6 (±0.8) | +5.8 (±1.0) | +10.8 (±1.2) | +10.9 (±0.9) | +11.8 (±1.2) | +15.2 (±1.5) |
| Jua EPT-2 HRRR | +12.2 (±0.4) | +10.6 (±2.4) | +11.5 (±1.1) | +9.5 (±0.7) | +11.4 (±0.8) | +19.7 (±2.3) |
| Jua EPT-2 Reasoning | +4.6 (±0.4) | -5.7 (±1.3) | +2.5 (±1.2) | +7.3 (±0.4) | +7.0 (±0.8) | +1.1 (±1.0) |
| Jua EPT-2e | +0.9 (±0.7) | -21.5 (±3.3) | -5.1 (±2.8) | +5.9 (±0.7) | +7.3 (±1.1) | -5.1 (±0.9) |
| Microsoft Aurora | -1.2 (±1.1) | -20.0 (±4.3) | -7.1 (±4.6) | +3.9 (±1.0) | +3.7 (±1.6) | -6.9 (±1.4) |
| ECMWF AIFS ENS (mean) | +0.4 (±0.5) | -21.3 (±2.6) | -2.8 (±1.9) | +4.5 (±0.8) | +6.1 (±0.9) | -5.1 (±1.7) |
| ECMWF AIFS | -1.3 (±0.6) | -23.9 (±2.7) | -5.0 (±2.0) | +2.0 (±0.8) | +4.6 (±1.5) | -5.0 (±2.3) |
| ECMWF ENS (mean) | -1.7 (±0.3) | -9.8 (±0.9) | -3.3 (±0.8) | +1.3 (±0.3) | +0.2 (±0.8) | -6.1 (±0.8) |
| NOAA GFS | -23.8 (±1.4) | -22.5 (±3.2) | -26.3 (±2.7) | -26.9 (±2.5) | -18.0 (±2.4) | -22.9 (±2.1) |
| DWD ICON Global | +5.6 (±0.9) | -3.6 (±1.3) | +3.3 (±1.6) | +4.1 (±1.3) | +8.4 (±0.7) | +10.2 (±1.9) |

## 2 m temperature — full horizon 6-240 h (6-hourly grid)

_(no data for track_a h6_240)_

## 2 m temperature — full horizon 1-48 h (hourly grid)

_(no data for track_a h1_48)_

# Local-tail per-country counts: gt_q95, h6_48, debiased

## track_a

| model | variable | positive countries |
|---|---|---|
| Jua EPT-2.1 Europa | temp | 9/13 |
| Jua EPT-2.1 Europa | solar | 4/9 |
| Jua EPT-2.1 Europa | wind | 11/13 |
| Jua EPT-2 HRRR | temp | 12/13 |
| Jua EPT-2 HRRR | solar | 3/9 |
| Jua EPT-2 HRRR | wind | 10/13 |
| Jua EPT-2 Reasoning | temp | 8/13 |
| Jua EPT-2 Reasoning | solar | 1/9 |
| Jua EPT-2 Reasoning | wind | 6/13 |
| Jua EPT-2e | temp | 3/13 |
| Jua EPT-2e | solar | 1/9 |
| Jua EPT-2e | wind | 5/13 |
| Microsoft Aurora | temp | 3/13 |
| Microsoft Aurora | wind | 6/13 |
| ECMWF AIFS ENS (mean) | temp | 5/13 |
| ECMWF AIFS ENS (mean) | wind | 5/13 |
| ECMWF AIFS | temp | 5/13 |
| ECMWF AIFS | wind | 5/13 |
| ECMWF ENS (mean) | temp | 1/13 |
| ECMWF ENS (mean) | wind | 6/13 |
| NOAA GFS | temp | 0/13 |
| NOAA GFS | solar | 9/9 |
| NOAA GFS | wind | 7/13 |
| DWD ICON Global | temp | 10/13 |
| DWD ICON Global | solar | 4/9 |
| DWD ICON Global | wind | 11/13 |
| Jua EPT-2.1 Helios | solar | 9/9 |

## track_b

| model | variable | positive countries |
|---|---|---|
| Jua EPT-2.1 Europa | temp | 12/13 |
| Jua EPT-2.1 Europa | solar | 3/8 |
| Jua EPT-2.1 Europa | wind | 11/13 |
| Jua EPT-2 HRRR | temp | 13/13 |
| Jua EPT-2 HRRR | solar | 1/8 |
| Jua EPT-2 HRRR | wind | 9/13 |
| DWD ICON-EU | temp | 11/13 |
| DWD ICON-EU | solar | 4/8 |
| DWD ICON-EU | wind | 11/13 |
| Jua EPT-2.1 Helios | solar | 8/8 |


# Track B (10 m wind speed), skill_pct vs IFS, debiased

## 10 m wind speed — full horizon 1-48 h (hourly grid)

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +6.5 (±0.3) | -0.7 (±0.9) | +2.4 (±0.3) | +8.3 (±0.5) | +7.3 (±0.3) | +9.3 (±1.5) |
| Jua EPT-2 HRRR | +2.5 (±0.7) | +4.4 (±1.1) | -2.4 (±1.7) | +3.4 (±0.5) | +1.9 (±0.2) | +4.2 (±1.7) |
| DWD ICON-EU | +4.6 (±0.4) | -1.5 (±1.1) | +1.2 (±0.6) | +5.0 (±0.5) | +3.1 (±0.2) | +10.4 (±1.8) |

## 10 m wind speed — lead 6 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +7.9 | -1.4 | +4.5 | +9.5 | +8.8 | +10.1 |
| Jua EPT-2 HRRR | +2.3 | +3.5 | -1.9 | +2.9 | +1.9 | +3.6 |
| DWD ICON-EU | +6.8 | -3.2 | +1.7 | +6.0 | +7.5 | +13.6 |

## 10 m wind speed — lead 12 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +8.6 | +1.4 | +5.5 | +9.6 | +9.3 | +11.0 |
| Jua EPT-2 HRRR | +3.2 | +4.6 | -1.0 | +3.8 | +2.8 | +4.8 |
| DWD ICON-EU | +7.0 | -1.7 | +2.2 | +6.0 | +7.2 | +13.8 |

## 10 m wind speed — lead 24 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +8.2 | +2.1 | +5.1 | +9.0 | +8.3 | +10.9 |
| Jua EPT-2 HRRR | +3.9 | +5.4 | -0.6 | +4.9 | +3.1 | +5.3 |
| DWD ICON-EU | +6.4 | -1.0 | +1.8 | +5.6 | +6.0 | +12.9 |

## 10 m wind speed — lead 48 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +7.7 | +2.0 | +4.2 | +7.7 | +8.3 | +11.3 |
| Jua EPT-2 HRRR | +4.6 | +6.1 | +0.6 | +4.8 | +4.2 | +6.7 |
| DWD ICON-EU | +4.7 | -1.8 | -0.2 | +2.8 | +4.2 | +12.7 |

# Track B (2 m temperature), skill_pct vs IFS, debiased

## 2 m temperature — full horizon 1-48 h (hourly grid)

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +13.4 (±0.6) | +7.9 (±0.9) | +11.9 (±1.5) | +12.5 (±1.3) | +13.5 (±0.4) | +16.8 (±2.0) |
| Jua EPT-2 HRRR | +12.2 (±0.6) | +14.6 (±2.3) | +15.0 (±1.2) | +9.2 (±0.3) | +8.8 (±1.0) | +17.5 (±3.3) |
| DWD ICON-EU | +12.5 (±0.8) | +9.5 (±0.7) | +11.9 (±1.4) | +10.7 (±1.2) | +11.3 (±1.4) | +17.4 (±2.8) |

## 2 m temperature — lead 6 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +10.9 | +5.7 | +9.2 | +10.5 | +11.4 | +12.9 |
| Jua EPT-2 HRRR | +12.1 | +11.9 | +14.1 | +8.9 | +10.2 | +17.3 |
| DWD ICON-EU | +13.8 | +8.9 | +13.0 | +11.8 | +13.1 | +18.6 |

## 2 m temperature — lead 12 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +14.8 | +8.2 | +13.9 | +14.1 | +15.1 | +17.2 |
| Jua EPT-2 HRRR | +14.3 | +12.5 | +15.9 | +11.4 | +12.3 | +19.6 |
| DWD ICON-EU | +15.1 | +9.0 | +13.2 | +13.4 | +14.6 | +20.1 |

## 2 m temperature — lead 24 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +13.4 | +9.0 | +12.9 | +12.4 | +14.3 | +15.3 |
| Jua EPT-2 HRRR | +12.5 | +13.8 | +15.5 | +9.7 | +10.0 | +17.0 |
| DWD ICON-EU | +13.3 | +9.4 | +13.0 | +11.0 | +13.6 | +17.4 |

## 2 m temperature — lead 48 h

| model | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | +13.7 | +8.5 | +13.4 | +12.8 | +13.6 | +16.3 |
| Jua EPT-2 HRRR | +12.4 | +14.2 | +16.0 | +9.4 | +9.3 | +17.2 |
| DWD ICON-EU | +10.7 | +8.5 | +10.7 | +8.5 | +9.2 | +15.8 |

# Track C (solar, 1 h shortwave accumulation), skill_pct vs IFS, debiased

## solar — full horizon 1-48 h (hourly grid)

_(no data for track_c h1_48)_

## solar — lead 6 h

_(no data for track_c lead_6)_

## solar — lead 12 h

_(no data for track_c lead_12)_

## solar — lead 24 h

_(no data for track_c lead_24)_

## solar — lead 48 h

_(no data for track_c lead_48)_

# Precipitation (1 h accumulation), skill_pct vs IFS, debiased, wet-hour regimes

Regimes: all / dry (<0.1 mm) / wet <P50 / P50-75 / P75-95 / >P95 of the ERA5 1991-2020 wet-hour climatology. Multiplicative debiasing (sum(obs)/sum(fc), trailing 4 wk, clip [0.33,3]).

## Track A

### precip — full horizon 1-48 h (hourly grid)

| model | all | dry | wet_lt_p50 | p50_p75 | p75_p95 | gt_p95 |
|---|---|---|---|---|---|---|
| Jua EPT-2 Reasoning | +5.1 (±0.4) | +2.2 (±1.3) | +9.3 (±0.6) | +14.0 (±0.9) | +10.6 (±0.8) | +1.7 (±0.5) |
| Jua EPT-2 HRRR | +1.3 (±1.3) | -6.1 (±3.3) | +9.3 (±1.8) | +15.2 (±2.2) | +10.2 (±1.2) | -1.5 (±0.5) |
| Jua EPT-2e | +3.3 (±1.1) | +1.5 (±4.8) | +7.7 (±1.1) | +14.8 (±1.7) | +8.8 (±1.5) | -1.9 (±0.9) |
| Jua EPT-2.1 Europa | +4.2 (±0.7) | +21.0 (±2.7) | -11.1 (±3.0) | -10.5 (±3.4) | -5.9 (±2.5) | +0.2 (±0.6) |
| NOAA GFS | -4.3 (±1.0) | -0.2 (±1.8) | -5.1 (±2.0) | -9.3 (±1.8) | -11.2 (±1.4) | -3.7 (±1.2) |
| DWD ICON Global | -1.4 (±1.7) | +8.3 (±2.7) | -14.4 (±2.7) | -14.4 (±3.0) | -9.8 (±2.2) | +0.0 (±0.4) |

### precip — lead 6 h

| model | all | dry | wet_lt_p50 | p50_p75 | p75_p95 | gt_p95 |
|---|---|---|---|---|---|---|
| Jua EPT-2 Reasoning | +1.8 | -2.4 | +3.3 | +7.9 | +6.7 | +1.3 |
| Jua EPT-2 HRRR | -4.0 | -19.9 | +4.1 | +11.8 | +6.5 | -2.9 |
| Jua EPT-2e | +6.0 | +26.4 | +18.5 | +13.8 | -1.8 | -7.3 |
| Jua EPT-2.1 Europa | -1.7 | +14.8 | -20.0 | -19.8 | -11.3 | -0.5 |
| ECMWF ENS (mean) | -4.8 | -33.2 | +7.7 | +20.3 | +12.8 | -1.5 |
| NOAA GFS | -11.1 | -22.5 | -13.9 | -17.0 | -15.3 | -1.7 |
| DWD ICON Global | -3.5 | +4.8 | -18.5 | -17.4 | -10.7 | -0.1 |

### precip — lead 12 h

| model | all | dry | wet_lt_p50 | p50_p75 | p75_p95 | gt_p95 |
|---|---|---|---|---|---|---|
| Jua EPT-2 Reasoning | +3.1 | -1.8 | +5.6 | +11.7 | +10.3 | +2.3 |
| Jua EPT-2 HRRR | -0.8 | -10.6 | +5.3 | +13.9 | +10.5 | -0.7 |
| Jua EPT-2e | -0.6 | -4.6 | -1.1 | +8.5 | +4.5 | -0.5 |
| Jua EPT-2.1 Europa | +5.9 | +24.2 | -12.6 | -10.6 | -5.7 | +1.5 |
| ECMWF ENS (mean) | +1.7 | -9.1 | +13.7 | +22.8 | +15.6 | -1.4 |
| NOAA GFS | -0.3 | +9.4 | -2.3 | -7.2 | -12.7 | -3.0 |
| DWD ICON Global | +3.8 | +19.9 | -9.5 | -11.1 | -7.9 | -0.2 |

### precip — lead 24 h

| model | all | dry | wet_lt_p50 | p50_p75 | p75_p95 | gt_p95 |
|---|---|---|---|---|---|---|
| Jua EPT-2 Reasoning | +5.0 | +1.9 | +9.4 | +15.3 | +11.7 | +1.8 |
| Jua EPT-2 HRRR | +1.6 | -6.0 | +9.3 | +16.2 | +11.9 | -0.2 |
| Jua EPT-2e | +1.4 | -3.7 | +3.0 | +13.8 | +9.7 | +0.1 |
| Jua EPT-2.1 Europa | +6.2 | +23.5 | -9.7 | -9.2 | -5.6 | +1.5 |
| ECMWF ENS (mean) | +2.7 | -9.0 | +17.6 | +25.3 | +17.0 | -0.6 |
| NOAA GFS | +0.3 | +9.6 | -0.1 | -6.2 | -10.8 | -3.1 |
| DWD ICON Global | +2.6 | +16.9 | -9.6 | -12.1 | -9.8 | -0.1 |

### precip — lead 48 h

| model | all | dry | wet_lt_p50 | p50_p75 | p75_p95 | gt_p95 |
|---|---|---|---|---|---|---|
| Jua EPT-2 Reasoning | +6.6 | +4.1 | +13.8 | +18.6 | +13.1 | +1.8 |
| Jua EPT-2 HRRR | +2.4 | -6.2 | +12.5 | +17.8 | +13.3 | +0.4 |
| Jua EPT-2e | +3.2 | -4.4 | +11.0 | +21.3 | +14.4 | +0.0 |
| Jua EPT-2.1 Europa | +5.4 | +18.7 | -7.2 | -5.2 | -2.5 | +1.0 |
| ECMWF ENS (mean) | +2.5 | -13.0 | +23.7 | +30.8 | +19.5 | -0.8 |
| NOAA GFS | -1.5 | +4.8 | -0.4 | -4.7 | -8.3 | -4.8 |
| DWD ICON Global | -1.1 | +6.2 | -9.8 | -10.7 | -7.0 | -1.6 |

## Track B

### precip — full horizon 1-48 h (hourly grid)

| model | all | dry | wet_lt_p50 | p50_p75 | p75_p95 | gt_p95 |
|---|---|---|---|---|---|---|
| Jua EPT-2 HRRR | +1.4 (±3.4) | -3.6 (±9.7) | +10.3 (±4.4) | +15.6 (±6.1) | +10.4 (±2.5) | -0.7 (±0.3) |
| Jua EPT-2.1 Europa | +7.8 (±0.9) | +29.3 (±1.4) | -19.1 (±6.0) | -20.2 (±7.2) | -9.0 (±5.7) | +1.2 (±0.8) |
| DWD ICON-EU | +3.5 (±0.5) | +15.3 (±0.3) | -10.9 (±2.7) | -11.4 (±3.8) | -6.9 (±2.2) | +0.1 (±0.5) |

## Heavy-precip (>P95) categorical detection, Track A, ≤48 h, debiased

| model | POD | FAR | CSI | freq bias |
|---|---|---|---|---|
| Jua EPT-2.1 Europa | 0.28 | 0.62 | 0.19 | 0.74 |
| DWD ICON Global | 0.29 | 0.65 | 0.19 | 0.82 |
| Jua EPT-2 Reasoning | 0.23 | 0.56 | 0.18 | 0.53 |
| ECMWF IFS | 0.25 | 0.65 | 0.17 | 0.71 |
| NOAA GFS | 0.25 | 0.66 | 0.17 | 0.74 |
| Jua EPT-2 HRRR | 0.20 | 0.53 | 0.16 | 0.42 |
| Jua EPT-2e | 0.20 | 0.55 | 0.16 | 0.44 |
| ECMWF ENS (mean) | 0.15 | 0.50 | 0.13 | 0.29 |

# Conditional bias fingerprint at lead 48 h (debiased, pooled cross-country)

| model | variable | bias lt_q5 | bias gt_q95 |
|---|---|---|---|
| Jua EPT-2.1 Europa | wind | +1.1 | -2.3 |
| Jua EPT-2 HRRR | wind | +1.0 | -2.3 |
| Jua EPT-2 Reasoning | wind | +1.0 | -2.6 |
| Jua EPT-2e | wind | +1.1 | -2.7 |
| Microsoft Aurora | wind | +1.1 | -2.6 |
| ECMWF AIFS ENS (mean) | wind | +1.2 | -2.8 |
| ECMWF AIFS | wind | +1.1 | -2.8 |
| ECMWF ENS (mean) | wind | +1.1 | -2.6 |
| NOAA GFS | wind | +0.9 | -2.3 |
| DWD ICON Global | wind | +1.1 | -2.2 |
| ECMWF IFS | wind | +1.0 | -2.5 |
| RANGE (wind) | wind | +0.9 .. +1.2 | -2.8 .. -2.2 |
| Jua EPT-2.1 Europa | temp | +2.3 | -1.2 |
| Jua EPT-2 HRRR | temp | +2.1 | -1.0 |
| Jua EPT-2 Reasoning | temp | +2.6 | -1.4 |
| Jua EPT-2e | temp | +3.0 | -1.5 |
| Microsoft Aurora | temp | +3.0 | -1.6 |
| ECMWF AIFS ENS (mean) | temp | +3.0 | -1.4 |
| ECMWF AIFS | temp | +3.0 | -1.3 |
| ECMWF ENS (mean) | temp | +2.6 | -1.5 |
| NOAA GFS | temp | +2.8 | -1.8 |
| DWD ICON Global | temp | +2.5 | -1.2 |
| ECMWF IFS | temp | +2.3 | -1.3 |
| RANGE (temp) | temp | +2.1 .. +3.0 | -1.8 .. -1.0 |

# Debias delta (debiased minus raw skill_pct), h6_48

| model | track/variable | all | lt_q5 | q5_q25 | q25_q75 | q75_q95 | gt_q95 |
|---|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | track_a wind | +7.2 | -38.2 | -13.9 | +12.9 | +21.7 | +13.9 |
| Jua EPT-2.1 Europa | track_a temp | -0.8 | +5.1 | +4.0 | -0.2 | -3.0 | -2.9 |
| Jua EPT-2 Reasoning | track_a wind | +0.1 | +3.3 | +0.8 | -0.1 | -0.4 | -0.6 |
| Jua EPT-2 Reasoning | track_a temp | +0.7 | +1.2 | -0.1 | +0.1 | +1.8 | +1.4 |
| Jua EPT-2.1 Europa | track_c solar (h1_48) | -- | -- | -- | -- | -- | -- |
| Jua EPT-2.1 Helios | track_c solar (h1_48) | -- | -- | -- | -- | -- | -- |

# Attribution inputs (mixed-effects left to the paper author)

Model attribute axes (config/matrix.yaml) joined with pooled gt_q95 skill at h6_48 (debiased). Replicate-level input for the mixed-effects model: `kind='country'` rows of final_aggregates.parquet (per-country skill + jackknife SE at all lead scopes, regimes all/q75_q95/gt_q95).

| model | family | training | output | domain | wind gt_q95 (±SE) | temp gt_q95 (±SE) |
|---|---|---|---|---|---|---|
| Jua EPT-2.1 Europa | jua | diffusion | ensemble | regional | +8.1 (±1.2) | +15.2 (±1.5) |
| Jua EPT-2 HRRR | jua | diffusion | ensemble | regional | +6.2 (±1.0) | +19.7 (±2.3) |
| Jua EPT-2 Reasoning | jua | regression | deterministic | global | -0.8 (±0.4) | +1.1 (±1.0) |
| Jua EPT-2e | jua | regression | ensemble | global | -6.9 (±0.6) | -5.1 (±0.9) |
| Microsoft Aurora | external | regression | deterministic | global | -3.5 (±0.6) | -6.9 (±1.4) |
| ECMWF AIFS ENS (mean) | external | proper_score | ensemble | global | -9.1 (±0.8) | -5.1 (±1.7) |
| ECMWF AIFS | external | regression | deterministic | global | -11.3 (±0.7) | -5.0 (±2.3) |
| ECMWF ENS (mean) | physics | physics | ensemble | global | -1.2 (±0.2) | -6.1 (±0.8) |
| NOAA GFS | physics | physics | deterministic | global | -0.1 (±0.8) | -22.9 (±2.1) |
| DWD ICON Global | physics | physics | deterministic | global | +9.1 (±1.2) | +10.2 (±1.9) |
| Jua EPT-2.1 Helios | ? | ? | ? | ? | -- | -- |
