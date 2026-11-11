# Battery command evidence — Stage A of #256

Tracking is observational: there are no new retries, fallback writes or recovery
settings. The existing driver call is made exactly once and retains its return
value/exception. Existing keepalive and battery-follow behavior remain in place.

Events distinguish queued, sent, reference_verified, physically_applied, failed,
unconfirmed and superseded. `failed` is scoped by its reason (transport not
confirmed or measured response outside tolerance), not proof that nothing reached
the device. `physically_applied` means fresh measured power was consistent with the
requested intent; it is not proof of causality or guaranteed hardware safety.

Generic HA power uses the oldest source last_reported/last_updated timestamp of all
contributing sensors, never cache-read time. Missing source time stays unconfirmed.
Local EnergyHub Modbus power is timestamped on successful read; a successful
reference readback is separately recorded. Other drivers do not get invented
freshness evidence. HA values that remain unchanged without source timestamp
updates can remain unconfirmed even if physically correct.

Default observation policy: 120 s settling, <=90 s source age, post-send timestamps,
future tolerance 5 s, target tolerance max(150 W,20%). These are observation defaults,
not hardware-calibrated recovery settings. SOC-limited and autonomous operation
stay unconfirmed rather than being diagnosed as command failure. Policy parameters
are explicit in Tracker and should be validated per integration before expansion.
Shadow mode never records a physical command as accepted.

Owner-only SQLite evidence is written via a 64-event bounded daemon queue to
`/data/battery-commands.sqlite3`. Set `EW_BATTERY_COMMAND_DB` to change the location
or `EW_BATTERY_COMMAND_TRACKING=0` to disable disk capture. At most 5,000 events and
30 days are retained; cleanup occurs on writes. Writer failure/queue saturation can
drop evidence. Pending events may be lost at process exit. Session IDs distinguish
restarts; persisted commands are never restored as authority or retried. Read with
`python scripts/report_battery_commands.py --limit 100`.

Stage B remains pending: choose hardware-validated drivers and define bounded,
idempotent retries, cancellation, supported fallback and restart behavior. No
universal HOLD command or automatic recovery is enabled by this PR.
