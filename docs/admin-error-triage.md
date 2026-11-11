# Owner/Admin error review (2026-11-11)

The 48-hour error groups are historical aggregates across installations. They
can include older builds after a fix has shipped. Current per-house errors use
a shorter window and match the latest reported build. Group counts alone do
not identify an exception's cause or prove that main is still affected.

Telemetry deliberately contains only module/location, exception class and build
version, never exception messages or full tracebacks. Keep that privacy boundary.
The Owner/Admin group rows now show the versions already supplied by the API.
Red means investigate, not proof of a programming defect: configuration and
storage problems can also appear there.

| Reported group | Source findings / next evidence |
| --- | --- |
| `nordpool.fetch_ha_nordpool_and_save: Error` | `Error` can be emitted by an error-marked print without an active exception. Need the affected build and sanitized local log; cannot infer HA authentication, data format, or network failure from this class. |
| `nordpool.fetch_ha_nordpool_and_save: ConnectionError` (#284) | A failed HA sensor request previously aborted the entire import, including usable data from another sensor. Connection failures and timeouts now warn locally and continue to the next configured sensor. The report alone does not establish whether DNS, refusal, TLS or another transport failure caused the outage; the affected installation's local log is still needed. |
| `nordpool.ensure_prices_exist: Error` | The missing-price critical message also produces generic `Error`. It can follow a failed fetch. Existing Swedish-source fallback and non-Swedish source restrictions remain intact. |
| `gpm.evaluate: TypeError` | Reproduced a remaining phase-reset defect: integer phase states allowed by the charger interface crash string-membership checks. Numeric strings also fail to request the intended phase reset. Fixed with numeric/label regression coverage. The reported group still needs build/location correlation to establish that it is this exact defect. |
| `ftw_deye-svk.poll: LuaError` | Main already guards the energy calculation when a failed register read leaves SoC nil. Need build and local Lua error to determine whether this is the older nil-arithmetic bug or another failure. No inverter writes/control safeguards changed. |
| `settings.save_ev_schedule_day: StringDataRightTruncation` | Main already migrates legacy `car_id VARCHAR(20)` to TEXT while loading schedules (#232). Existing database regression covers long IDs. Need build and actual column/error details before attributing the report to that limit or adding another migration. |
| `decisions.check_spa_schedule_plan: TypeError` | Main already rejects unavailable/non-finite water temperatures (#230), with regression coverage. Need build and local traceback to diagnose any remaining operand/model issue. |
| `pump.read_sensors: Error` | Explicit connection failures, missing responses and Modbus error responses can all print generic `Error`. Need local message; this does not establish a software defect. |
| `logger.log_status: DiskFull` | Storage-capacity incident requiring the affected host/database evidence. No historical data deletion, retention change or production storage modification is part of this fix. |

The GPM fix accepts integer `1`/`3`, numeric strings and existing HA labels.
Unknown/missing values do not trigger a phase reset. Fuse/current limits and
the existing phase-switch behavior for string labels are preserved.

For #284, a fetch with no usable prices still returns failure without writing
prices or marking the refresh successful. Existing stored prices remain intact.
Swedish installations retain the existing public-source fallback; other countries
never substitute Swedish prices. A subsequent normal engine cycle can retry.
Unexpected parsing/programming and database errors retain the error log path.
No extra HTTP retries, timeout changes or TLS-verification changes were added.
