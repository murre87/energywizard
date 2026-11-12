# Owner/Admin error review (2026-11-12)

The 48-hour error groups are historical aggregates across installations. They
can include older builds after a fix has shipped. Current per-house errors use
a shorter window and match the latest reported build. Group counts alone do
not identify an exception's cause or prove that main is still affected.

Telemetry deliberately contains only module/location, exception class and build
version, never exception messages or full tracebacks. Keep that privacy boundary.
The Owner/Admin group rows now show the versions already supplied by the API.
Red means investigate, not proof of a programming defect: configuration and
storage problems can also appear there.

| Reported group | Issue | Fix / findings |
| --- | --- | --- |
| `nordpool.fetch_ha_nordpool_and_save: Error` | #211 | Invalid HA JSON and Czech unit misconfig now warn (`⚠️`). Unexpected exceptions still `❌`. Any `requests` transport error warns and keeps another sensor's prices (#284). |
| `nordpool.fetch_api_and_save` | #211 | elprisetjustnu.se timeout, connection, non-200 and bad JSON warn. Unexpected exceptions still `❌`. |
| `nordpool.ensure_prices_exist: Error` | #210 | Missing-today KRITISKT no longer uses `❌` (was classified as generic `Error` without an exception). |
| `gpm.evaluate: TypeError` | #282 / #208 | Only old builds `47090f7` / `a662a27`. Main normalizes `current_price=None` and stringifies phase states. Houses need update. |
| `ftw_deye-svk.poll: LuaError` | #297 / #215 | Nil-SoC energy headroom guarded; self-heal now requires numeric `bat_w`. Still need local Lua text if reports continue on current builds. |
| `settings.save_ev_schedule_day: StringDataRightTruncation` | #298 / #232 | Save paths now migrate `car_id` VARCHAR→TEXT before INSERT (previously only on load). |
| `logger.log_status: DiskFull` | #250 | DiskFull / SQLSTATE 53100 logged as `⚠️` (host storage), not program error. |
| `pump.read_sensors: Error` / `ConnectionResetError` | #299 | Modbus connect/timeout/reset and empty replies warn; unexpected exceptions stay `❌`. |

Swedish installations retain the public-source fallback when HA prices fail;
other countries never substitute Swedish prices. No retention/deletion changes
were made for DiskFull beyond reclassifying the log line.
