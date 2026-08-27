# Hardware Validation Report

- **Generated (UTC):** 2026-08-27 11:54:08 UTC
- **Database dialect:** sqlite
- **Scope:** all test runs currently in the database

## Executive Summary

240 test runs across 6 PVT corners were analysed, for an overall yield of 90.0%. The weakest corner was COLD_LOWV at 86.0% yield. 127 anomaly finding(s) were sourced from anomaly_event table.

## Yield Summary by Corner

| corner     |   n_runs |   n_pass |   n_fail |   yield_pct |   VDD_CORE_V_mean |   VDD_CORE_V_std |   ICC_MA_mean |   ICC_MA_std |   TJ_C_mean |   TJ_C_std |   JITTER_PS_mean |   JITTER_PS_std |
|:-----------|---------:|---------:|---------:|------------:|------------------:|-----------------:|--------------:|-------------:|------------:|-----------:|-----------------:|----------------:|
| COLD_LOWV  |       43 |       37 |        6 |       86.05 |            0.7599 |         0.005338 |         203   |       10.86  |      -35.93 |     3.458  |            12.69 |           5.516 |
| COLD_NOMV  |       38 |       36 |        2 |       94.74 |            0.7996 |         0.005802 |         252.7 |        9.477 |      -34.8  |     3.848  |            11.37 |           2.045 |
| HOT_HIGHV  |       36 |       33 |        3 |       91.67 |            0.8389 |         0.006301 |         305.7 |       14.41  |      131    |     2.632  |            22.67 |           3.204 |
| HOT_NOMV   |       44 |       38 |        6 |       86.36 |            0.7997 |         0.00443  |         249.9 |        8.2   |      129.8  |     2.646  |            23.48 |           5.217 |
| ROOM_HIGHV |       34 |       30 |        4 |       88.24 |            0.8397 |         0.006566 |         300   |       13.54  |       30.55 |     0.4333 |            17.5  |           6.504 |
| ROOM_NOMV  |       45 |       42 |        3 |       93.33 |            0.7998 |         0.003473 |         251.5 |        9.583 |       29.82 |     2.632  |            16.14 |           3.805 |

## Process Capability (Cp / Cpk)

| param_name   | unit   |     n |     mean |        std |     cp |    cpk |   limit_low |   limit_high |
|:-------------|:-------|------:|---------:|-----------:|-------:|-------:|------------:|-------------:|
| VDD_CORE_V   | V      | 11520 |   0.8041 |   0.02737  | 0.8526 | 0.7809 |        0.74 |         0.88 |
| VDD_IO_V     | V      | 11520 |   1.8    |   0.004171 | 7.192  | 7.18   |        1.71 |         1.89 |
| ICC_MA       | mA     | 11520 | 257.7    |  35.79     | 1.956  | 1.512  |        0    |       420    |
| TJ_C         | degC   | 11520 |  41.42   |  68.39     | 0.4752 | 0.4212 |      -45    |       150    |
| CLK_MHZ      | MHz    | 11520 | 399.9    |   0.3474   | 3.838  | 3.779  |      396    |       404    |
| JITTER_PS    | ps     | 11520 |  17.28   |   6.504    | 1.153  | 0.8859 |        0    |        45    |
| LEAK_UA      | uA     | 11520 | 111.2    | 171.4      | 0.7294 | 0.2162 |        0    |       750    |
| VOH_V        | V      | 11520 |   1.748  |   0.02804  | 2.199  | 1.685  |        1.52 |         1.89 |

## Figures

### pareto
![pareto](/home/claude/nxp-hw-validation-agent/artifacts/figures/yield_pareto.png)

### wafer
![wafer](/home/claude/nxp-hw-validation-agent/artifacts/figures/wafer_map_all.png)

### corr
![corr](/home/claude/nxp-hw-validation-agent/artifacts/figures/correlation_heatmap.png)

### anomaly
![anomaly](/home/claude/nxp-hw-validation-agent/artifacts/figures/anomaly_scores.png)

### box_VDD_CORE_V
![box_VDD_CORE_V](/home/claude/nxp-hw-validation-agent/artifacts/figures/corner_boxplot_VDD_CORE_V.png)

### box_ICC_MA
![box_ICC_MA](/home/claude/nxp-hw-validation-agent/artifacts/figures/corner_boxplot_ICC_MA.png)

### box_TJ_C
![box_TJ_C](/home/claude/nxp-hw-validation-agent/artifacts/figures/corner_boxplot_TJ_C.png)

### box_JITTER_PS
![box_JITTER_PS](/home/claude/nxp-hw-validation-agent/artifacts/figures/corner_boxplot_JITTER_PS.png)

### timeseries
![timeseries](/home/claude/nxp-hw-validation-agent/artifacts/figures/parameter_timeseries_run15.png)

## Anomaly Findings

Source: anomaly_event table

|   run_id | severity   | param_name   | failure_mode       |   score | model_name   | explanation                                                                                           |
|---------:|:-----------|:-------------|:-------------------|--------:|:-------------|:------------------------------------------------------------------------------------------------------|
|       89 | CRITICAL   |              | ldo_ripple         |  1      | fused        | VDD_CORE_V_frac_oor high (z=+147.9); CLK_MHZ_std high (z=+121.5); CLK_MHZ_ripple high (z=+120.1)      |
|      238 | CRITICAL   |              | ldo_ripple         |  0.9984 | fused        | VDD_CORE_V_frac_oor high (z=+160.2); CLK_MHZ_std high (z=+117.3); CLK_MHZ_ripple high (z=+116.1)      |
|       67 | CRITICAL   |              | ldo_ripple         |  0.9921 | fused        | JITTER_PS_frac_oor high (z=+192.3); CLK_MHZ_std high (z=+75.3); CLK_MHZ_ripple high (z=+74.6)         |
|       26 | CRITICAL   |              | ldo_ripple         |  0.9874 | fused        | JITTER_PS_frac_oor high (z=+183.6); CLK_MHZ_std high (z=+81.8); CLK_MHZ_ripple high (z=+81.0)         |
|      233 | CRITICAL   |              | ldo_ripple         |  0.978  | fused        | CLK_MHZ_std high (z=+84.6); CLK_MHZ_ripple high (z=+83.7); CLK_MHZ_roughness high (z=+66.7)           |
|       98 | CRITICAL   |              | thermal_runaway    |  0.9756 | fused        | TJ_C_std high (z=+254.5); LEAK_UA_frac_oor high (z=+234.2); TJ_C_slope high (z=+183.6)                |
|       79 | CRITICAL   |              | vdd_droop          |  0.9756 | fused        | VDD_CORE_V_slope low (z=-104.5); CLK_MHZ_std high (z=+88.6); CLK_MHZ_slope low (z=-81.6)              |
|       91 | CRITICAL   |              | ldo_ripple         |  0.9677 | fused        | CLK_MHZ_std high (z=+90.7); CLK_MHZ_ripple high (z=+89.9); CLK_MHZ_roughness high (z=+53.3)           |
|       13 | CRITICAL   |              | ldo_ripple         |  0.9654 | fused        | CLK_MHZ_std high (z=+117.7); CLK_MHZ_ripple high (z=+116.5); CLK_MHZ_range high (z=+55.9)             |
|      137 | CRITICAL   |              | vdd_droop          |  0.9614 | fused        | VDD_CORE_V_slope low (z=-110.0); CLK_MHZ_std high (z=+86.5); CLK_MHZ_slope low (z=-86.1)              |
|      206 | CRITICAL   |              | thermal_runaway    |  0.9543 | fused        | TJ_C_std high (z=+277.9); LEAK_UA_frac_oor high (z=+234.2); TJ_C_slope high (z=+200.1)                |
|      164 | CRITICAL   |              | vdd_droop          |  0.9543 | fused        | VDD_CORE_V_slope low (z=-105.8); CLK_MHZ_std high (z=+86.9); CLK_MHZ_slope low (z=-82.4)              |
|      203 | CRITICAL   |              | ldo_ripple         |  0.9543 | fused        | CLK_MHZ_std high (z=+123.3); CLK_MHZ_ripple high (z=+122.2); CLK_MHZ_roughness high (z=+93.9)         |
|       24 | CRITICAL   |              | vdd_droop          |  0.9402 | fused        | VDD_CORE_V_slope low (z=-130.1); CLK_MHZ_std high (z=+103.5); CLK_MHZ_slope low (z=-100.9)            |
|      162 | CRITICAL   |              | clock_jitter_drift |  0.9394 | fused        | JITTER_PS_slope high (z=+74.1); JITTER_PS_frac_oor high (z=+52.4); droop_depth high (z=+12.5)         |
|      149 | CRITICAL   |              | clock_jitter_drift |  0.9331 | fused        | JITTER_PS_frac_oor high (z=+139.8); JITTER_PS_slope high (z=+72.1); JITTER_PS_std high (z=+11.4)      |
|      236 | CRITICAL   |              | clock_jitter_drift |  0.922  | fused        | JITTER_PS_slope high (z=+73.6); JITTER_PS_std high (z=+11.7); JITTER_PS_p95 high (z=+5.2)             |
|       62 | CRITICAL   |              | iddq_leakage_shift |  0.9181 | fused        | LEAK_UA_frac_oor high (z=+431.4); LEAK_UA_slope high (z=+77.3); leakage_temp_slope high (z=+24.2)     |
|      179 | CRITICAL   |              | clock_jitter_drift |  0.9165 | fused        | JITTER_PS_slope high (z=+70.8); JITTER_PS_frac_oor high (z=+52.4); JITTER_PS_std high (z=+11.2)       |
|      191 | CRITICAL   |              | clock_jitter_drift |  0.9102 | fused        | JITTER_PS_slope high (z=+71.4); JITTER_PS_std high (z=+11.5); JITTER_PS_frac_oor high (z=+8.6)        |
|      111 | CRITICAL   |              | clock_jitter_drift |  0.9094 | fused        | JITTER_PS_frac_oor high (z=+87.4); JITTER_PS_slope high (z=+73.0); JITTER_PS_std high (z=+11.8)       |
|      190 | CRITICAL   |              | thermal_runaway    |  0.9079 | fused        | TJ_C_std high (z=+186.5); TJ_C_slope high (z=+136.7); LEAK_UA_frac_oor high (z=+110.9)                |
|      204 | CRITICAL   |              | clock_jitter_drift |  0.9071 | fused        | JITTER_PS_slope high (z=+73.2); JITTER_PS_frac_oor high (z=+17.4); JITTER_PS_std high (z=+11.6)       |
|      209 | HIGH       |              | clock_jitter_drift |  0.8858 | fused        | JITTER_PS_slope high (z=+73.1); JITTER_PS_frac_oor high (z=+52.4); JITTER_PS_std high (z=+11.6)       |
|      196 | HIGH       |              | vdd_droop          |  0.878  | fused        | VDD_CORE_V_slope low (z=-80.6); CLK_MHZ_std high (z=+65.3); CLK_MHZ_slope low (z=-63.9)               |
|      171 | HIGH       |              | iddq_leakage_shift |  0.8591 | fused        | VDD_CORE_V_frac_oor high (z=+12.2); droop_depth high (z=+12.2); VDD_CORE_V_range high (z=+12.2)       |
|      165 | HIGH       |              | thermal_runaway    |  0.8551 | fused        | TJ_C_std high (z=+198.2); TJ_C_slope high (z=+144.4); TJ_C_range high (z=+107.3)                      |
|       87 | HIGH       |              | clock_jitter_drift |  0.852  | fused        | JITTER_PS_frac_oor high (z=+8.6); JITTER_PS_ripple high (z=+8.6); JITTER_PS_range high (z=+8.6)       |
|        4 | HIGH       |              | thermal_runaway    |  0.8457 | fused        | TJ_C_std high (z=+208.7); TJ_C_slope high (z=+151.2); TJ_C_range high (z=+110.6)                      |
|       49 | HIGH       |              | iddq_leakage_shift |  0.8362 | fused        | VDD_CORE_V_range high (z=+12.5); droop_depth high (z=+12.5); VDD_CORE_V_std high (z=+12.4)            |
|       14 | HIGH       |              | thermal_runaway    |  0.8323 | fused        | TJ_C_std high (z=+186.7); TJ_C_slope high (z=+135.7); TJ_C_range high (z=+98.4)                       |
|      121 | HIGH       |              | vdd_droop          |  0.7874 | fused        | VDD_CORE_V_slope low (z=-97.6); CLK_MHZ_std high (z=+88.0); CLK_MHZ_slope low (z=-76.9)               |
|       90 | HIGH       |              | iddq_leakage_shift |  0.7803 | fused        | LEAK_UA_frac_oor high (z=+12.2); LEAK_UA_range high (z=+12.2); LEAK_UA_std high (z=+12.2)             |
|      182 | HIGH       |              | iddq_leakage_shift |  0.778  | fused        | VOH_V_range high (z=+2.3); corner_COLD_LOWV high (z=+2.1); ICC_MA_p05 low (z=-2.1)                    |
|       85 | HIGH       |              | thermal_runaway    |  0.7465 | fused        | TJ_C_std high (z=+219.7); TJ_C_slope high (z=+159.3); TJ_C_range high (z=+117.3)                      |
|      180 | HIGH       |              | vdd_droop          |  0.7346 | fused        | VDD_CORE_V_slope low (z=-77.4); CLK_MHZ_std high (z=+70.1); CLK_MHZ_slope low (z=-59.5)               |
|      132 | HIGH       |              | iddq_leakage_shift |  0.7283 | fused        | TJ_C_ripple high (z=+2.8); TJ_C_std high (z=+2.6); TJ_C_range high (z=+2.5)                           |
|      127 | HIGH       |              | iddq_leakage_shift |  0.7197 | fused        | VDD_CORE_V_slope low (z=-18.2); VDD_CORE_V_frac_oor high (z=+12.2); VDD_CORE_V_range high (z=+12.2)   |
|      231 | HIGH       |              | thermal_runaway    |  0.7094 | fused        | TJ_C_std high (z=+243.6); TJ_C_slope high (z=+175.7); TJ_C_range high (z=+129.4)                      |
|       94 | HIGH       |              | iddq_leakage_shift |  0.7055 | fused        | VOH_V_range high (z=+3.1); corner_HOT_HIGHV high (z=+2.4); VDD_IO_V_max high (z=+2.3)                 |
|      135 | HIGH       |              | iddq_leakage_shift |  0.7024 | fused        | VDD_IO_V_p05 low (z=-3.5); VDD_IO_V_min low (z=-2.7); corner_HOT_NOMV high (z=+2.2)                   |
|      108 | MEDIUM     |              | thermal_runaway    |  0.6866 | fused        | TJ_C_std high (z=+298.3); TJ_C_slope high (z=+214.1); TJ_C_range high (z=+159.8)                      |
|       59 | MEDIUM     |              | iddq_leakage_shift |  0.6858 | fused        | corner_HOT_HIGHV high (z=+2.4); ICC_MA_p95 high (z=+2.3); ICC_MA_mean high (z=+2.3)                   |
|      220 | MEDIUM     |              | iddq_leakage_shift |  0.6858 | fused        | TJ_C_slope low (z=-2.7); corner_COLD_LOWV high (z=+2.1); VDD_IO_V_slope high (z=+2.1)                 |
|      214 | MEDIUM     |              | iddq_leakage_shift |  0.6827 | fused        | ICC_MA_frac_oor high (z=+12.2); ICC_MA_range high (z=+12.2); ICC_MA_std high (z=+12.2)                |
|       35 | MEDIUM     |              | iddq_leakage_shift |  0.6591 | fused        | corner_COLD_LOWV high (z=+2.1); part_number_S32K344 high (z=+1.9); VOH_V_roughness low (z=-1.9)       |
|       27 | MEDIUM     |              | iddq_leakage_shift |  0.6551 | fused        | corner_COLD_LOWV high (z=+2.1); part_number_i.MX93 high (z=+2.1); ICC_MA_min low (z=-2.0)             |
|       23 | MEDIUM     |              | iddq_leakage_shift |  0.6543 | fused        | VOH_V_range high (z=+2.9); VDD_IO_V_range high (z=+2.6); corner_HOT_NOMV high (z=+2.2)                |
|      234 | MEDIUM     |              | iddq_leakage_shift |  0.648  | fused        | JITTER_PS_slope high (z=+2.5); corner_HOT_NOMV high (z=+2.2); VDD_IO_V_mean high (z=+2.1)             |
|      188 | MEDIUM     |              | iddq_leakage_shift |  0.6441 | fused        | corner_HOT_HIGHV high (z=+2.4); VOH_V_range high (z=+2.1); VDD_IO_V_p95 high (z=+2.0)                 |
|      100 | MEDIUM     |              | thermal_runaway    |  0.6425 | fused        | TJ_C_std high (z=+255.3); TJ_C_slope high (z=+184.4); TJ_C_range high (z=+135.5)                      |
|       77 | MEDIUM     |              | iddq_leakage_shift |  0.6409 | fused        | VDD_IO_V_roughness high (z=+2.7); corner_COLD_LOWV high (z=+2.1); VDD_IO_V_p95 high (z=+2.1)          |
|      115 | MEDIUM     |              | thermal_runaway    |  0.6386 | fused        | TJ_C_std high (z=+247.0); TJ_C_slope high (z=+178.2); TJ_C_range high (z=+129.3)                      |
|       20 | MEDIUM     |              | iddq_leakage_shift |  0.637  | fused        | VOH_V_roughness high (z=+3.4); VOH_V_std high (z=+2.5); VOH_V_ripple high (z=+2.5)                    |
|        6 | MEDIUM     |              | iddq_leakage_shift |  0.6354 | fused        | VDD_CORE_V_slope high (z=+2.7); VOH_V_ripple high (z=+2.3); CLK_MHZ_slope high (z=+2.3)               |
|      170 | MEDIUM     |              | iddq_leakage_shift |  0.6307 | fused        | VOH_V_range high (z=+2.7); VDD_IO_V_p05 low (z=-2.5); corner_COLD_LOWV high (z=+2.1)                  |
|      148 | MEDIUM     |              | iddq_leakage_shift |  0.6291 | fused        | leakage_temp_slope low (z=-3.2); corner_HOT_HIGHV high (z=+2.4); CLK_MHZ_p05 low (z=-1.5)             |
|       82 | MEDIUM     |              | iddq_leakage_shift |  0.6236 | fused        | TJ_C_slope low (z=-3.1); VDD_CORE_V_slope low (z=-2.9); VDD_IO_V_roughness high (z=+2.8)              |
|      232 | MEDIUM     |              | iddq_leakage_shift |  0.6165 | fused        | corner_HOT_HIGHV high (z=+2.4); VDD_IO_V_p95 high (z=+2.4); CLK_MHZ_range high (z=+2.1)               |
|      141 | MEDIUM     |              | iddq_leakage_shift |  0.615  | fused        | corner_ROOM_HIGHV high (z=+2.4); TJ_C_range high (z=+2.2); ICC_MA_p05 high (z=+1.9)                   |
|      136 | MEDIUM     |              | iddq_leakage_shift |  0.6071 | fused        | VDD_IO_V_p95 high (z=+2.3); corner_COLD_LOWV high (z=+2.1); part_number_i.MX93 high (z=+2.1)          |
|       66 | MEDIUM     |              | iddq_leakage_shift |  0.6055 | fused        | VOH_V_roughness high (z=+2.8); VOH_V_range high (z=+2.8); VOH_V_ripple high (z=+2.8)                  |
|       56 | MEDIUM     |              | iddq_leakage_shift |  0.6039 | fused        | corner_HOT_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1); CLK_MHZ_roughness low (z=-1.8)       |
|      193 | MEDIUM     |              | iddq_leakage_shift |  0.6024 | fused        | corner_COLD_LOWV high (z=+2.1); VDD_IO_V_p95 low (z=-2.1); VDD_IO_V_mean low (z=-2.1)                 |
|       80 | MEDIUM     |              | iddq_leakage_shift |  0.5906 | fused        | corner_HOT_NOMV high (z=+2.2); VDD_IO_V_mean low (z=-1.9); part_number_S32K344 high (z=+1.9)          |
|        2 | MEDIUM     |              | iddq_leakage_shift |  0.5843 | fused        | JITTER_PS_slope low (z=-2.8); leakage_temp_slope high (z=+2.2); corner_ROOM_NOMV high (z=+2.1)        |
|      222 | MEDIUM     |              | iddq_leakage_shift |  0.5835 | fused        | corner_HOT_NOMV high (z=+2.2); TJ_C_std low (z=-2.0); TJ_C_roughness low (z=-1.9)                     |
|      157 | MEDIUM     |              | iddq_leakage_shift |  0.5827 | fused        | corner_HOT_HIGHV high (z=+2.4); TJ_C_std low (z=-2.3); TJ_C_ripple low (z=-2.3)                       |
|      187 | MEDIUM     |              | iddq_leakage_shift |  0.5819 | fused        | corner_HOT_NOMV high (z=+2.2); VDD_IO_V_p95 low (z=-1.7); CLK_MHZ_p95 low (z=-1.7)                    |
|      140 | MEDIUM     |              | iddq_leakage_shift |  0.5646 | fused        | VOH_V_slope high (z=+2.8); corner_HOT_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1)            |
|      228 | MEDIUM     |              | iddq_leakage_shift |  0.563  | fused        | corner_HOT_HIGHV high (z=+2.4); VDD_IO_V_min low (z=-2.3); part_number_S32K344 high (z=+1.9)          |
|      129 | MEDIUM     |              | iddq_leakage_shift |  0.5583 | fused        | VDD_IO_V_max high (z=+2.4); corner_HOT_NOMV high (z=+2.2); VDD_IO_V_range high (z=+2.1)               |
|      230 | MEDIUM     |              | iddq_leakage_shift |  0.5535 | fused        | corner_COLD_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1); TJ_C_slope low (z=-2.0)             |
|      199 | MEDIUM     |              | clock_jitter_drift |  0.5512 | fused        | JITTER_PS_slope high (z=+8.6); JITTER_PS_frac_oor high (z=+8.6); JITTER_PS_range high (z=+8.6)        |
|      225 | MEDIUM     |              | iddq_leakage_shift |  0.5496 | fused        | VDD_IO_V_p05 low (z=-2.9); corner_ROOM_HIGHV high (z=+2.4); VDD_IO_V_range high (z=+2.3)              |
|       15 | MEDIUM     |              | iddq_leakage_shift |  0.5402 | fused        | TJ_C_slope high (z=+2.5); corner_HOT_HIGHV high (z=+2.4); LEAK_UA_p05 high (z=+2.3)                   |
|       76 | MEDIUM     |              | iddq_leakage_shift |  0.5394 | fused        | corner_HOT_HIGHV high (z=+2.4); VDD_IO_V_roughness high (z=+2.3); TJ_C_roughness high (z=+2.2)        |
|      207 | MEDIUM     |              | iddq_leakage_shift |  0.5378 | fused        | corner_HOT_NOMV high (z=+2.2); LEAK_UA_min high (z=+1.9); LEAK_UA_p95 high (z=+1.9)                   |
|      160 | MEDIUM     |              | iddq_leakage_shift |  0.5378 | fused        | VDD_IO_V_min low (z=-2.8); VDD_IO_V_p95 low (z=-2.8); corner_COLD_LOWV high (z=+2.1)                  |
|      217 | MEDIUM     |              | iddq_leakage_shift |  0.5354 | fused        | corner_HOT_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1); CLK_MHZ_min low (z=-1.9)             |
|      212 | MEDIUM     |              | iddq_leakage_shift |  0.5299 | fused        | CLK_MHZ_slope high (z=+2.6); corner_HOT_HIGHV high (z=+2.4); VDD_IO_V_p95 low (z=-2.2)                |
|      153 | MEDIUM     |              | iddq_leakage_shift |  0.5283 | fused        | CLK_MHZ_slope high (z=+2.5); corner_HOT_HIGHV high (z=+2.4); VDD_CORE_V_slope high (z=+1.7)           |
|       12 | MEDIUM     |              | iddq_leakage_shift |  0.5205 | fused        | corner_HOT_HIGHV high (z=+2.4); JITTER_PS_roughness high (z=+1.9); part_number_MPC5748G high (z=+1.6) |
|       19 | MEDIUM     |              | iddq_leakage_shift |  0.5079 | fused        | VDD_IO_V_range high (z=+3.0); VDD_IO_V_min low (z=-2.4); TJ_C_ripple high (z=+2.4)                    |
|       50 | MEDIUM     |              | iddq_leakage_shift |  0.5008 | fused        | VOH_V_slope high (z=+2.6); corner_HOT_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1)            |
|      213 | MEDIUM     |              | iddq_leakage_shift |  0.4969 | fused        | corner_HOT_HIGHV high (z=+2.4); VOH_V_slope high (z=+2.0); TJ_C_ripple low (z=-2.0)                   |
|      183 | MEDIUM     |              | iddq_leakage_shift |  0.4945 | fused        | corner_HOT_NOMV high (z=+2.2); jitter_ripple_ratio high (z=+1.7); leakage_temp_slope high (z=+1.6)    |
|       57 | MEDIUM     |              | iddq_leakage_shift |  0.4937 | fused        | VDD_IO_V_p95 high (z=+2.9); corner_COLD_LOWV high (z=+2.1); CLK_MHZ_std low (z=-1.9)                  |
|      116 | MEDIUM     |              | iddq_leakage_shift |  0.4929 | fused        | corner_HOT_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1); TJ_C_ripple high (z=+2.0)            |
|      166 | MEDIUM     |              | iddq_leakage_shift |  0.4921 | fused        | corner_HOT_NOMV high (z=+2.2); part_number_S32K344 high (z=+1.9); TJ_C_range high (z=+1.5)            |
|      143 | MEDIUM     |              | iddq_leakage_shift |  0.4913 | fused        | corner_HOT_HIGHV high (z=+2.4); JITTER_PS_roughness high (z=+1.9); VOH_V_std low (z=-1.6)             |
|      133 | MEDIUM     |              | iddq_leakage_shift |  0.489  | fused        | corner_HOT_HIGHV high (z=+2.4); part_number_i.MX93 high (z=+2.1); LEAK_UA_p95 high (z=+1.8)           |
|      197 | MEDIUM     |              | iddq_leakage_shift |  0.4843 | fused        | corner_HOT_HIGHV high (z=+2.4); VOH_V_ripple high (z=+2.2); VOH_V_std high (z=+2.1)                   |
|      119 | MEDIUM     |              | iddq_leakage_shift |  0.4811 | fused        | corner_HOT_HIGHV high (z=+2.4); TJ_C_ripple high (z=+2.3); TJ_C_std high (z=+2.3)                     |
|       93 | MEDIUM     |              | iddq_leakage_shift |  0.4811 | fused        | corner_HOT_NOMV high (z=+2.2); VOH_V_std low (z=-1.6); VOH_V_ripple low (z=-1.6)                      |
|       29 | MEDIUM     |              | iddq_leakage_shift |  0.4795 | fused        | corner_HOT_HIGHV high (z=+2.4); CLK_MHZ_range high (z=+2.2); CLK_MHZ_min low (z=-2.0)                 |
|       86 | MEDIUM     |              | iddq_leakage_shift |  0.4732 | fused        | corner_ROOM_HIGHV high (z=+2.4); CLK_MHZ_slope low (z=-1.5); part_number_SJA1110 high (z=+1.5)        |
|      210 | MEDIUM     |              | iddq_leakage_shift |  0.4724 | fused        | TJ_C_slope high (z=+2.1); part_number_i.MX93 high (z=+2.1); corner_ROOM_NOMV high (z=+2.1)            |
|       37 | MEDIUM     |              | iddq_leakage_shift |  0.4669 | fused        | leakage_temp_slope high (z=+2.5); corner_HOT_NOMV high (z=+2.2); LEAK_UA_min high (z=+1.7)            |
|      101 | MEDIUM     |              | iddq_leakage_shift |  0.4622 | fused        | corner_HOT_HIGHV high (z=+2.4); ICC_MA_mean high (z=+1.9); ICC_MA_p95 high (z=+1.9)                   |
|      124 | MEDIUM     |              | iddq_leakage_shift |  0.4591 | fused        | corner_HOT_HIGHV high (z=+2.4); LEAK_UA_p95 high (z=+2.1); LEAK_UA_mean high (z=+2.1)                 |
|      145 | MEDIUM     |              | iddq_leakage_shift |  0.4543 | fused        | VOH_V_slope high (z=+3.2); VDD_IO_V_slope high (z=+2.4); corner_COLD_LOWV high (z=+2.1)               |
|        5 | MEDIUM     |              | iddq_leakage_shift |  0.4512 | fused        | CLK_MHZ_range high (z=+2.4); corner_ROOM_HIGHV high (z=+2.4); TJ_C_ripple low (z=-1.8)                |
|      192 | MEDIUM     |              | iddq_leakage_shift |  0.4496 | fused        | VDD_IO_V_roughness high (z=+2.7); VOH_V_roughness high (z=+2.1); corner_ROOM_NOMV high (z=+2.1)       |
|       16 | MEDIUM     |              | iddq_leakage_shift |  0.4488 | fused        | corner_HOT_NOMV high (z=+2.2); part_number_i.MX93 high (z=+2.1); VOH_V_slope high (z=+2.0)            |
|      128 | MEDIUM     |              | iddq_leakage_shift |  0.4488 | fused        | corner_HOT_NOMV high (z=+2.2); TJ_C_roughness high (z=+1.7); CLK_MHZ_max low (z=-1.6)                 |
|      125 | MEDIUM     |              | iddq_leakage_shift |  0.4465 | fused        | TJ_C_slope high (z=+2.7); VDD_IO_V_p05 low (z=-2.5); corner_ROOM_HIGHV high (z=+2.4)                  |
|      144 | MEDIUM     |              | iddq_leakage_shift |  0.4441 | fused        | VOH_V_slope low (z=-2.8); CLK_MHZ_range high (z=+2.5); VDD_IO_V_slope low (z=-2.1)                    |
|       55 | MEDIUM     |              | iddq_leakage_shift |  0.4425 | fused        | VDD_IO_V_p95 high (z=+2.9); VDD_IO_V_roughness high (z=+2.6); corner_COLD_NOMV high (z=+2.2)          |
|       51 | MEDIUM     |              | iddq_leakage_shift |  0.437  | fused        | corner_ROOM_HIGHV high (z=+2.4); VDD_IO_V_p95 low (z=-2.1); part_number_i.MX93 high (z=+2.1)          |
|        3 | MEDIUM     |              | iddq_leakage_shift |  0.437  | fused        | corner_COLD_NOMV high (z=+2.2); part_number_S32K344 high (z=+1.9); VDD_IO_V_slope high (z=+1.8)       |
|       52 | MEDIUM     |              | iddq_leakage_shift |  0.4346 | fused        | VDD_IO_V_slope low (z=-2.7); corner_COLD_LOWV high (z=+2.1); part_number_i.MX93 high (z=+2.1)         |
|        8 | MEDIUM     |              | iddq_leakage_shift |  0.4331 | fused        | corner_COLD_LOWV high (z=+2.1); VDD_CORE_V_p05 low (z=-1.7); supply_setpoint_v low (z=-1.6)           |
|       64 | MEDIUM     |              | iddq_leakage_shift |  0.4283 | fused        | corner_ROOM_NOMV high (z=+2.1); part_number_S32K344 high (z=+1.9); TJ_C_range low (z=-1.8)            |
|       71 | MEDIUM     |              | iddq_leakage_shift |  0.4268 | fused        | corner_COLD_LOWV high (z=+2.1); CLK_MHZ_roughness low (z=-2.0); CLK_MHZ_std low (z=-1.9)              |
|       70 | MEDIUM     |              | iddq_leakage_shift |  0.4252 | fused        | VOH_V_slope low (z=-2.6); VDD_IO_V_slope low (z=-2.3); corner_HOT_NOMV high (z=+2.2)                  |
|      173 | MEDIUM     |              | iddq_leakage_shift |  0.4252 | fused        | VOH_V_range low (z=-2.6); VOH_V_ripple low (z=-2.3); VOH_V_std low (z=-2.2)                           |
|       83 | MEDIUM     |              | iddq_leakage_shift |  0.4252 | fused        | corner_HOT_NOMV high (z=+2.2); LEAK_UA_min high (z=+2.2); LEAK_UA_p05 high (z=+2.2)                   |
|       58 | MEDIUM     |              | iddq_leakage_shift |  0.4205 | fused        | corner_HOT_NOMV high (z=+2.2); jitter_ripple_ratio high (z=+2.1); VDD_IO_V_roughness low (z=-2.0)     |
|      216 | MEDIUM     |              | iddq_leakage_shift |  0.4197 | fused        | TJ_C_roughness high (z=+2.7); corner_HOT_NOMV high (z=+2.2); CLK_MHZ_range high (z=+2.2)              |
|       11 | MEDIUM     |              | iddq_leakage_shift |  0.4134 | fused        | VDD_IO_V_mean high (z=+2.4); corner_ROOM_HIGHV high (z=+2.4); VOH_V_roughness low (z=-2.2)            |
|      202 | MEDIUM     |              | iddq_leakage_shift |  0.4118 | fused        | corner_HOT_HIGHV high (z=+2.4); CLK_MHZ_range low (z=-2.1); TJ_C_roughness high (z=+1.8)              |
|      211 | MEDIUM     |              | iddq_leakage_shift |  0.4094 | fused        | corner_HOT_NOMV high (z=+2.2); leakage_temp_slope low (z=-2.1); LEAK_UA_p05 high (z=+2.1)             |
|      194 | MEDIUM     |              | iddq_leakage_shift |  0.4047 | fused        | corner_HOT_NOMV high (z=+2.2); VOH_V_range high (z=+1.6); VOH_V_min low (z=-1.6)                      |
|      120 | MEDIUM     |              | iddq_leakage_shift |  0.4047 | fused        | CLK_MHZ_std high (z=+2.6); CLK_MHZ_ripple high (z=+2.5); VDD_IO_V_p05 high (z=+2.2)                   |
|      154 | MEDIUM     |              | iddq_leakage_shift |  0.4039 | fused        | corner_HOT_NOMV high (z=+2.2); LEAK_UA_p05 high (z=+1.6); LEAK_UA_mean high (z=+1.6)                  |
|       63 | MEDIUM     |              | iddq_leakage_shift |  0.4031 | fused        | VDD_IO_V_mean high (z=+2.6); corner_COLD_LOWV high (z=+2.1); part_number_S32K344 high (z=+1.9)        |

## Appendix: SQL Query Traceability

**Per-corner run counts (summary_table)**
```sql
SELECT id, corner, status FROM test_run {where}
```

**Per-corner key-parameter mean/std (summary_table)**
```sql
SELECT tr.corner AS corner, m.param_name AS param_name, m.value AS value FROM measurement m JOIN test_run tr ON tr.id = m.run_id {where}
```

**Spec limits (cpk_table)**
```sql
SELECT param_name, unit, limit_low, limit_high FROM test_limit
```

**Raw measurements for Cpk (cpk_table)**
```sql
SELECT param_name, value FROM measurement {where}
```

**Anomaly findings**
```sql
SELECT run_id, severity, param_name, failure_mode, score, model_name, explanation FROM anomaly_event {where} ORDER BY score DESC
```

**Representative run selection**
```sql
SELECT id FROM test_run {where} ORDER BY started_at DESC LIMIT 1
```

**Parameter timeseries (plot_parameter_timeseries)**
```sql
SELECT param_name, sample_idx, value, unit FROM measurement WHERE run_id = :rid ORDER BY param_name, sample_idx
```

**Corner boxplot data (plot_corner_boxplot)**
```sql
SELECT tr.corner AS corner, m.value AS value, m.unit AS unit FROM measurement m JOIN test_run tr ON tr.id = m.run_id WHERE m.param_name = :p
```

**Yield Pareto data (plot_yield_pareto)**
```sql
SELECT param_name FROM measurement WHERE passed = 0
```

**Correlation heatmap data (plot_correlation_heatmap)**
```sql
SELECT run_id, param_name, value FROM measurement
```

**Wafer map data (plot_wafer_map)**
```sql
SELECT d.die_x AS die_x, d.die_y AS die_y, tr.status AS status FROM test_run tr JOIN dut d ON d.id = tr.dut_id {where}
```
