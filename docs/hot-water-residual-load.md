# Source-dated hot-water residual reconstruction — #407

Use a private, local measurement capture:

```text
python scripts/reconstruct_hot_water_load.py measurements.json
```

The offline tool reconstructs:

```text
residual W = grid_import W + PV_generation W - battery_charge W - hot_water_electrical W
```

Grid export and battery discharge are negative. All measurements must describe
the same AC household boundary. DC-side EnergyHub battery/PV values cannot simply
be substituted for these AC measurements. Physical boundaries, signs, clock
alignment and meter identity require installation qualification; input declarations
do not prove them. No uploads, database reads/writes, device calls or runtime
forecast changes occur.

Input has `contract` and `samples`. The required contract is:

```json
{"boundary":"ac_household","grid_sign":"import_positive",
 "battery_sign":"charge_positive","excluded_loads":["hot_water"]}
```

Each measurement row includes:

| Role | Watts | Source date | Timestamp basis |
|---|---|---|---|
| Grid | `grid_w` | `grid_sample_at` | `grid_basis` |
| PV | `pv_w` | `pv_sample_at` | `pv_basis` |
| Battery | `battery_w` | `battery_sample_at` | `battery_basis` |
| Hot water | `hot_water_power_w` | `hot_water_power_sample_at` | `hot_water_power_basis` |

`timestamp` is the row's observation/log time. All four source dates are separately
required: offset-aware ISO times or UTC epoch seconds. A row's insertion time is
never substituted for missing measurement dates. PV and hot-water watts must be
nonnegative. Zero is an explicit valid measurement, not the absence of a device.
Nonfinite, boolean, missing or inconsistent energy-balance readings are rejected.

Default policy: all source dates must be no later than the row time and at most
90 seconds old, with at most 5 seconds between oldest/newest channel timestamps.
Only `source` and `ha_report` bases are accepted by default. `--allow-receipt`
explicitly accepts `local_receipt` for offline comparison without relabelling it
as device sample time or switching the preferred local REST route to cloud.
Age/skew/gap/coverage policies are explicit CLI options; policy acceptance is not
physical freshness or synchronized-device-clock proof.

Consecutive valid samples use the existing left-hold physical UTC-quarter
integrator, with a default 90-second maximum gap. The left sample's source
evidence must remain fresh through the whole interval; otherwise that interval
is excluded. Invalid rows stay gaps and are never removed to connect their valid
neighbours. The final sample is never extrapolated beyond the capture.

At least 90% observed quarter coverage is required by default. `kw` is the residual
average over the covered portion, `coverage` records that portion and
`covered_energy_kwh` accounts only for measured duration. An accepted partial
quarter does not claim complete energy coverage. Repeated DST wall hours retain
distinct physical UTC keys; duplicate physical timestamps are refused.

Only hot water is excluded. Inputs with existing `controlled_w` exclusions or
`hot_water_kw` reservations are refused to prevent subtracting the same load twice.
EV/other separately planned loads are not silently removed. Their exclusion and
future addition require their own complete aligned measurements before adoption.

Output `rows` use the existing offline forecast evaluator's `t`/`kw` quarter
format, plus explicit coverage/energy. The quality report counts rejected samples,
rejected intervals and timestamp bases from validated sample components; it does
not dump raw captures, entity IDs or endpoints. `adoption_ready` is always false.
Input is limited to 50 MB/100,000 rows.

The optional power logging from PR #416 supplies the dedicated hot-water value and
its date/basis only. It does not invent the other channel timestamps. Existing
minute logs without those dates remain unqualified for this reconstruction.
Actual recorded data, measured boundary validation, chronological forecast/economic
comparison and runtime integration remain required; synthetic tests are not a
real-household performance or hardware qualification result.
