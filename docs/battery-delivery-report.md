# Battery plan delivery report

This is reporting only. It does not alter learning, savings definitions, planning,
commands or recovery. It builds on local snapshots (#253).

Minute-level sensor records now include the current captured plan ID and decision
rule. This identifies the intended plan, not proof that its commands took effect.
Historical rows without IDs and missing/dropped snapshots stay unscored. Snapshot
retention bounds how far back evidence is available.

Run from an engine environment with its normal database credentials:

```
python scripts/report_battery_delivery.py --start 2026-11-11T00:00:00+01:00 --end 2026-11-11T06:00:00+01:00
```

The command reads local snapshot files and `sensor_log` only. It prints JSON;
there are no uploads or new UI controls. Windows must be <=7 days and offset-aware.
Use `--directory` if snapshot capture uses a nondefault directory.

Integration uses the left sample as constant power until the next sample, only
when both have finite grid/battery measurements and are at most 90 seconds apart.
This approximation is explicit; longer gaps are never filled as zero or silently
extrapolated. Intervals split at slot boundaries and captured plan replacements.
Unknown replacement times remain uncovered. Repeated DST hours are distinct UTC
instants. Changing rule metadata is labelled unknown across the sample interval.

Positive grid means import; positive battery means charging. Captured full buy/sell
tariffs price measured grid energy, excluding wear, switch/reversal penalties and
terminal energy value. This is an energy-cost estimate, not an audited invoice.
Planned and measured costs are compared over identical covered intervals. A full
window difference is null unless coverage is complete. No counterfactual savings
or causal diagnosis is invented. Existing savings reporting remains unchanged.

Where aligned finite PV samples also exist, household power is grid - battery + PV;
forecast differences compare against captured household plus separately planned EV
demand and solar. These have their own coverage counter. All forecasts are effective
styled/corrected planning inputs, not necessarily raw weather/model predictions.
