# Household-load comparison — evaluation stage of #257

This change does not replace a runtime forecast, change control or add a trained
ML model. It validates input signals and provides a causal comparison harness.
Actual installation benchmarking and paired downstream economics remain pending.

At the AC household boundary, positive grid power is import and positive battery
power is charging:

    household = grid + PV - battery_charge
    baseline_target = household - explicitly_excluded_controlled_loads

All inputs are watts at aligned timestamps. PV/excluded loads are nonnegative;
missing readings and inconsistent negative residuals invalidate the interval.
`controlled_w` is an explicit list, not guessed equipment discovery. Subtract only
loads that are separately planned and will be added back to future total demand.
Do not remove heat pump/spa demand if it remains part of the forecast target, or
subtract the same device twice. Incorrect sign/measurement boundaries can invalidate
the comparison. A missing controlled-load measurement is not zero.

Input JSON is an array of local measurements, for example:

```
[{"timestamp":"2026-11-11T00:00:00+01:00","grid_w":2200,"pv_w":0,
  "battery_w":200,"controlled_w":[500]}]
```

Supply actual history, including all sample timestamps, and run:

```
python scripts/evaluate_household_forecast.py samples.json --split 2026-11-11T00:00:00+01:00
```

Inputs are limited to 50 MB. No uploads, live reads, device writes or settings edits
occur. Reconstruct physical UTC quarters with >=90% coverage; hold the left sample
only until the next finite sample within 90 seconds. Longer gaps stay excluded.
Repeated local DST hours retain distinct physical quarter keys.

Predeclared minimum evaluation: 672 valid training quarters (one week's worth) and
96 held-out quarters. Prefer multiple representative weeks and seasonal datasets
before drawing conclusions. A frozen weekday/hour p85 profile is clamped 1–6 kW,
with 2.5 kW sparse-key fallback, matching the current baseline's statistical shape.
It is fitted to the reconstructed signal, not a replay of the old import-only
training data or a claim about the exact forecast historically issued by the engine.

Candidate: 50% of that baseline and 50% median of available completed recent-hour
quarters plus matching local quarters yesterday/last week. These supports must
precede the forecast origin; earlier test observations can feed subsequent origins
in the documented rolling evaluation. The candidate falls back to baseline when
support is missing; it does not require a new dependency or model.

The report gives matched-sample MAE/RMSE and predictions. The forecast-error gate is
>=5% relative MAE improvement without increased RMSE. This is only an evaluation
criterion, not permission to enable anything. `adoption_ready` is always false:
paired planner-cost/constraint evaluation on recorded inputs, real household data,
and a reviewed opt-in rollout/reversion decision are still required. A lower MAE
alone does not establish economic improvement.
