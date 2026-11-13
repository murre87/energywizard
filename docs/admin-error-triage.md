# Owner/Admin error review (2026-11-12)

The 48-hour error groups are historical aggregates across installations. They
can include older builds after a fix has shipped. Current per-house errors use
a shorter window and match the latest reported build. Group counts alone do
not identify an exception's cause or prove that main is still affected.

Error metadata contains module/location, exception class and build version;
do not add raw exception messages or full tracebacks to those fields. Since
PR #301, reports can also include a bounded, sanitized support excerpt, enabled
by default with an opt-out in Settings. This is not a full-log upload. Keep the
existing redaction and size limits when using that evidence.
The Owner/Admin group rows now show the versions already supplied by the API.
Red means investigate, not proof of a programming defect: configuration and
storage problems can also appear there.

| Reported group | Issue | Fix / findings |
| --- | --- | --- |
| `nordpool.fetch_ha_nordpool_and_save: Error` | #211 | Invalid HA JSON and Czech unit misconfig now warn (`⚠️`). Unexpected exceptions still `❌`. Any `requests` transport error warns and keeps another sensor's prices (#284). |
| `nordpool.ensure_prices_exist: Error` | #210 | Missing-today KRITISKT no longer uses `❌` (was classified as generic `Error` without an exception). |
| `gpm.evaluate: TypeError` | #282 / #208 | Only old builds `47090f7` / `a662a27`. Main normalizes `current_price=None` and stringifies phase states. Houses need update. |
| `ftw_deye-svk.poll: LuaError` | #297 / #215 | Nil-SoC energy headroom guarded; self-heal now requires numeric `bat_w`. A failed Modbus read returns `(nil, err)` without raising; `read_rated_w` and `detect_hv` no longer index that nil, so poll keeps running while rated power is still unknown. |
| `settings.save_ev_schedule_day: StringDataRightTruncation` | #298 / #232 | Save paths now migrate `car_id` VARCHAR→TEXT before INSERT (previously only on load). |
| `logger.log_status: DiskFull` | #250 | DiskFull / SQLSTATE 53100 logged as `⚠️` (host storage), not program error. |
| `pump.read_sensors: Error` / `ConnectionResetError` | #299 | Modbus connect/timeout/reset and empty replies warn; unexpected exceptions stay `❌`. |
| `homeassistant.update_states: ConnectionError` | #228 | Connection drops and timeouts stay `⚠️` even after many tries. HTTP errors other than 401/502/503/504 and unexpected exceptions still `❌`. |

Swedish installations retain the public-source fallback when HA prices fail;
other countries never substitute Swedish prices. No retention/deletion changes
were made for DiskFull beyond reclassifying the log line.

## Issue #282 follow-up verification (2026-11-12)

Reviewed the issue body and all three comments against main `bca59e3`.
The two maintainer comments report the GPM TypeError only on `47090f7` and
`a662a27` (nine houses, 121 reports); they do not report recurrence on current
main. PR #283's phase-state normalization and PR #300's explicit-None-price
regression are already merged. No additional control change is justified by
that historical group alone.

Verification on Python 3.11 with disposable PostgreSQL 17 and Lua available:
**68 passed, no skips** across `test_gpm_generic`, `test_admin_error_groups_ui`,
`test_telemetry`, `test_logger_diskfull`, `test_deye_svk_poll`,
`test_ui_translations`, `test_sun_and_spa`, `test_settings_schedules`,
`test_spa_schedule` and `test_support_bundle`. The collector's separate
`test_app.py` suite passed **nine tests** using temporary SQLite databases.
These checks cover numeric/text phase reset, missing price, escaped build
versions, collector grouping, telemetry fields, schedule migration, unavailable
spa temperature, failed Deye reads and support redaction. They are local
regression evidence, not a new production telemetry query or hardware test.

Remaining verification before closing the umbrella issue:

- Confirm affected installations updated and that GPM errors do not recur on
  the updated build. Record the build and observation window; historical
  48-hour group totals can remain after an update.
- Keep unresolved price, Deye, storage and pump reports with their linked
  issues. Request sanitized local context for a current-build recurrence;
  warning classification does not restore connectivity, prices or disk space.
- PR #315 is still open for FTW Lua error context. Its follow-up is separate
  from the already-merged Deye failed-read guards.

No live installation, device command, retention policy or deployment was changed.
