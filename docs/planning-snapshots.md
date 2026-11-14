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

## Battery SOC provenance

New runtime captures pass the battery reading used to build the plan into SOC
quality diagnostics. `age_s` uses its original timestamp at planning time; repeated
cache reads do not reset it. `source` identifies `ha_reported`, `ha_updated`,
`ferroamp_mqtt_received`, or `modbus_received`. HA report/update timestamps and host
MQTT/Modbus receipt times are not proof of the battery's device measurement time.
Broker delay, integration caching and hardware polling can add unknown latency.

Generic HA aggregates require valid dated values from every configured SOC bank;
their oldest timestamp and weaker update basis are reported. Existing partial-bank
SOC calculation is preserved, but its age remains unknown. Ferroamp FTW dates the
actual SOC source: a latched EnergyHub SOC keeps its own receipt through unrelated
power updates; ESO fallback uses the oldest SOC contributor. Undated/retained MQTT
data do not acquire receipt times. Other FTW drivers remain undated.

Absent, mismatched, invalid or future evidence leaves age unknown. The legacy
`soc_age_s` settings key is no longer used as evidence. These fields are diagnostic
only: optimizer decisions, device commands, freshness/control gates and snapshot
schema/replay contracts are unchanged. No physical control qualification is implied.

## Storage status

The owner can open Settings → Planning snapshots in the web UI and refresh its
status: disabled, waiting for a first capture, queued, saving, saved, or failed.
Last successful save and failed/dropped attempt counts are shown. Counts cover
the current engine process and reset on restart; a successful save retains the
counts while clearing the current failed state. Queue saturation counts as a
dropped attempt; validation or storage errors count as failed attempts.

The capture path updates only in-memory counters. A separate daemon publishes
allowlisted diagnostics through the existing shared database, independently of
the snapshot writer. It checks every five seconds, publishing changes or a
60-second heartbeat. Database statements have a two-second timeout. A blocked
writer or status publisher never makes capture wait for disk or database work.
No configuration, paths, exception messages or snapshot contents are published.

The owner-only `/api/snapshot-status` endpoint rejects malformed, oversized,
unsupported, stale (>90 seconds) or implausibly future reports. Missing or failed
publication/database access is shown as unknown, never as a successful current
save. A full snapshot disk can be reported using the independent database; if the
database is also unavailable, only unknown status is possible. Pending counters
can be lost at process exit, and this report does not prove historical retention
or that storage remains writable after the last successful save. English and
Czech labels are included. Snapshot schema and replay behavior are unchanged.
