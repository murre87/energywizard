# End-to-end hot-water handover replay — #407

Run the scheduling, temperature-evidence and shadow-cycle components together:

```text
python scripts/evaluate_hot_water_shadow.py frozen-request.json --journal private/hot-water.json
```

This is a local, offline qualification path. It has no device/driver/network calls,
does not run in the engine, and never changes live control, shadow settings, GPM or
battery plans in the database. Every output has `simulation_only: true` and
`control_ready: false`. Simulated acknowledgements are supplied explicitly; no
tick implies that a command was accepted or delivered by hardware.

The frozen JSON combines the existing contracts:

- `request` and `prices`: [deadline proposal inputs](hot-water-planning.md), with
  offset-aware times, explicit duration/electrical input power and full import prices.
- `policy`: cycle target Celsius, maximum runtime seconds, temperature age limit,
  transport label, `local_rest_enabled` and explicit `allow_receipt` policy.
  Maximum runtime must accommodate the requested heating duration. Enabled local
  REST requires `nibe_local`; unavailable evidence never triggers cloud fallback.
- `observation`: normalized [temperature evidence](hot-water-observations.md),
  with `value_c`, epoch `sample_at` and `timestamp_basis`. The initial observation
  must pass the explicit freshness policy. `temperature_role_verified: true` is
  required: the configured water sensor is not automatically a qualified tank-top
  or charging sensor. This declaration is an input contract, not hardware proof.
- `forecast`: original residual battery-input quarters (`t`, `load_kw`, plus any
  solar/EV/buy/sell fields). `baseline_contract: "hot_water_excluded"` is required.
  Actual signed/aligned measurements must establish this exclusion. A whole-house
  forecast or already-reserved input is refused.
- `events`: chronological [cycle ticks and simulated acknowledgements](hot-water-shadow-cycle.md).
  At most 256 events and 144 forecast quarters are accepted. Input is limited to 2 MB.

The report includes the selected proposal, compact lifecycle frames and the final
remaining-load forecast. Each frame reports remaining electrical energy where it
can be determined. Every reservation is rebuilt from the original baseline, never
added to a previous result. Partial quarters account only for remaining overlap;
early target completion clears future simulated load after an explicit release
acknowledgement. The original input is not mutated.

Pending, uncertain, storage-error or interrupted cycles return no forecast rather
than assuming an action succeeded or another controller's load disappeared.
`reservation_available` means an advisory reservation can be constructed, not that
control is qualified. A cancelled cycle is not a satisfied hot-water demand.
An import-cost proposal is not a joint battery/PV optimum or measured savings.

A fingerprint binds the proposal, policy and frozen residual forecast to the
simulation journal. Changed context interrupts the old cycle; a completed old
cycle cannot certify a new request. Only the hash is stored, not raw input/config.
Restart cannot restore old action authority. Use a new explicit simulation journal
for a new scenario. It is single-owner storage, not a multi-process control lock.

Tests exercise the actual four components together, including existing pure battery
optimizer accounting, partial-quarter energy, early release, ambiguity, restart,
context changes, local preference and refusal to double-count baseline load.
No real household recording or physical heater was used to qualify this milestone.

Remaining runtime integration needs comfort/deadline/cycle semantics backed by actual
temperature/power data, a qualified bounded timed-boost/release interface, readback
and ownership reconciliation, runtime precedence, measured residual forecasts and
user-facing status. These offline components must not directly authorize actuator
writes. Local REST remains the preferred enabled transport throughout that work.

## Comfort and trigger-age input policy

Instead of an explicit `request`, the evaluator accepts epoch-second `now`,
`comfort_policy`, optional `demand_state` and optional `last_trigger_at`.
`hot_water_demand.derive` supplies the request to the same complete-price scheduler.
No runtime configuration or thermal thresholds are enabled automatically.

The policy must explicitly provide all of:

```json
{
  "comfort_c": 50,
  "target_c": 55,
  "max_trigger_age_s": 7200,
  "min_trigger_interval_s": 3600,
  "comfort_window_s": 1800,
  "comfort_bypasses_interval": true,
  "duration_min": 15,
  "electrical_power_kw": 2,
  "max_age_s": 90,
  "allow_receipt": true
}
```

These are synthetic replay values, not recommended heater settings. Target,
temperature-age and receipt policies must match the lifecycle `policy`. Tank
sensor role qualification and local-REST preference remain required.

`last_trigger_at` means externally supplied actual accepted-command history,
not target attainment, hygiene completion or a simulated acknowledgement. This
input must be grounded in recorded evidence; the tool cannot verify a caller's
declaration. The reducer never derives trigger success from a warm reading.

With no trigger history, the first fresh evaluation anchors the age window and
reports `history_known: false`. A subsequent evaluation must reuse the returned
`demand_state`; omitting that state starts a new scenario and cannot establish a
stable deadline. State is returned in the report, not automatically restored from
the separate shadow-cycle journal. A future runtime adapter must persist it.

Repeated cold observations preserve the first comfort anchor. Its window and the
trigger-age deadline jointly bound completion; normal trigger spacing applies
unless explicit comfort bypass is enabled. Recovered comfort clears that comfort
episode, while the age anchor remains fixed. Only newer supplied trigger history
resets the trigger-age anchor. A fresh target already reached needs no request.
Missing/stale evidence, changed policy or clock rollback produces no request.

Overdue demand and spacing conflicts are reported as `deadline_missed` or
`interval_conflict`. A missed deadline is not replaced with a new immediate
heating window. Complete permitted prices are still required; missing prices do
not cause an immediate start. Existing GPM critical-temperature and hygiene
behavior is unchanged and is not replaced by this advisory policy.

This covers explicit comfort/price-deferral and trigger-age semantics for replay.
It does not yet provide production comfort/hygiene guarantees, real cycle-success
evidence, an automatic runtime adapter or permission to control the heater.
