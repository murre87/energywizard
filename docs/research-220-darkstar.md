# Darkstar review — #220

Reviewed 2026-11-13: Darkstar
[`4d8d010f61c77eb499a012bf21e43b6a913f460c`](https://github.com/ergetie/darkstar/tree/4d8d010f61c77eb499a012bf21e43b6a913f460c)
against EnergyWizard `00f4d51`. Recommendation: adopt bounded observability and
input-quality ideas through independent implementations; retain our planner,
drivers and safeguards. No upstream code or dependencies were adopted.

## Evidence and overlap

Darkstar's [architecture](https://github.com/ergetie/darkstar/blob/4d8d010f61c77eb499a012bf21e43b6a913f460c/docs/ARCHITECTURE.md)
describes a MILP planner, forecast/learning layers and an executor. That is a
different system design, not evidence that replacing our optimizer improves a
shared workload. Its
[preflight checks](https://github.com/ergetie/darkstar/blob/4d8d010f61c77eb499a012bf21e43b6a913f460c/planner/preflight.py)
separate configuration, SOC, charger/deadline, price, forecast and numeric checks;
the SOC timestamp check warns when old and skips when no timestamp is supplied.
It is not a blanket stale-data rejection policy.

EnergyWizard already has reproducible local snapshots (`plan_snapshot.py`),
delivery coverage (`plan_delivery.py`), observational command tracking
(`battery_commands.py`) and offline forecast comparison
(`load_forecast_evaluation.py`). Extend those instead of introducing parallel
storage/control loops.

## Ranked proposals

| Priority | Bounded addition | Target and acceptance | Estimate |
| --- | --- | --- | --- |
| 1 | Snapshot persistence health | `plan_snapshot.py`: expose disabled, queued, last successful save and bounded failure/drop status without raw configuration/error dumps. Full disk/queue and a later success must be observable; no writer wait in the control tick. | 0.5–1 day |
| 2 | Input-quality evidence in replay | Record age, source, coverage and unknown/missing status for effective SOC/prices/forecasts. Version the snapshot schema and preserve replay of old snapshots. First report quality; any new dispatch rejection needs separate behavior review. | 1–2 days |
| 3 | EV goal-at-risk context | Extend `ev_missed.py` explanations with the active goal/plan identity and any observed allocation shortfall. Superseded goals and stale diagnostics cannot explain the current goal. Keep existing fuse, priority and minimum-current protection. | 1–2 days plus hardware validation |

The persistence proposal is grounded in Darkstar's
[plan-save health state](https://github.com/ergetie/darkstar/blob/4d8d010f61c77eb499a012bf21e43b6a913f460c/planner/plan_store_status.py),
which keeps a failed-save warning until a later success. Our snapshot worker
currently catches save failures to protect control but publishes no equivalent
status. Use safe counters/codes rather than copying raw upstream exception text.

The EV proposal is informed by
[goal-risk classification](https://github.com/ergetie/darkstar/blob/4d8d010f61c77eb499a012bf21e43b6a913f460c/executor/goal_risk.py),
which relates pause notifications to deadline, goal freshness and planned
shortfall. Its numeric thresholds are project choices, not validated defaults
for EnergyWizard.

## Defer or reject

- Do not replace our optimizer/forecast stack without shared chronological
  datasets, replayable inputs, feasibility checks and economic comparisons.
  #255/#257 provide better starting points for that evidence.
- Do not adopt the upstream
  [time-current fuse approximation](https://github.com/ergetie/darkstar/blob/4d8d010f61c77eb499a012bf21e43b6a913f460c/executor/fuse_model.py)
  to permit more current: its source describes approximate, uncertified curves.
  Existing hard current limits remain authoritative.
- No automatic recovery writes or online policy tuning are proposed by this
  review. Those remain separate, hardware-qualified work under #256/#257.

The pinned [license](https://github.com/ergetie/darkstar/blob/4d8d010f61c77eb499a012bf21e43b6a913f460c/LICENSE)
is AGPL-3.0; any future copied material still requires provenance and notice
review. This is a source review, not a benchmark, licensing opinion or observed
installation outcome. It completes the requested research scope.
