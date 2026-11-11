# Local battery-planning snapshots

The engine captures normalized effective inputs and the pure optimizer result to
`/data/planning-snapshots`. It does not upload data. Treat load/price histories as
private installation data even though credentials and entity names are excluded.
Set `EW_PLAN_SNAPSHOTS=0` to disable capture or `EW_PLAN_SNAPSHOT_DIR` to choose a
local directory. Owner-only files are atomically replaced. Retention is at most
96 files, each <=2 MB, and seven days; cleanup runs on successful writes.
A one-item queue drops evidence when storage is slow. A stalled or failed writer
cannot wait on the control loop. Pending evidence may be lost on shutdown.

Inputs are the final styled/corrected load/solar and full buy/sell tariffs passed
to `battery_plan.optimize`, initial energy, physical/capability limits and all
optimizer defaults. No settings/environment dump is captured. Output uses an
explicit field allowlist. The SHA-256 of the planner source identifies code;
canonical content hashing identifies the plan. Slot times require UTC offsets
and consecutive physical quarters. Capture rejects unsupported/non-finite data.

Run `python scripts/replay_battery_plan.py snapshot.json` from the same checkout.
Replay invokes only the pure optimizer, never live services or devices. It checks
schema, code and content identity, then requires exactly equal actions and numeric
results; deterministic action enumeration supplies tie-breaking. A different
planner version is rejected; use the original code to replay its evidence. This
is not a guarantee of numeric portability between arbitrary Python environments.

This supports planning diagnostics, not reproduction of every runtime error.
It does not alter optimizer decisions, device commands or savings definitions.
