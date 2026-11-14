# Hot-water temperature evidence — #407

The normalized heat-pump `read_state()` includes `dhw_temp_observation`:
`value_c`, `sample_at` (UTC epoch seconds or null), and `timestamp_basis`.
Existing `dhw_temp` values and driver control methods retain their behavior.
This observation describes the configured `water_temp` sensor, not automatically
a verified tank-top/charging-temperature binding for every heat-pump model.

- HA entity sensors use `last_reported`, falling back to `last_updated`, labelled
  `ha_report`. Re-reading the cache does not refresh these timestamps. An HA
  report date is not proof of an independent physical sample at that instant.
- myUplink uses the configured point's offset-aware `timestamp`, labelled
  `source`. Missing or invalid point dates stay unknown; response arrival is
  never substituted for source time.
- NIBE local REST uses its existing `_received_at`, labelled `local_receipt`.
  It remains receipt-only evidence, not a claimed device measurement timestamp.
- Drivers without date evidence retain an unknown observation timestamp.

`hot_water_observation.assess` requires an explicit clock and positive maximum
age. It distinguishes unknown, future, stale, receipt_only and fresh. Receipt-only
evidence is not classified fresh unless explicitly accepted by the caller.
Invalid/nonfinite or out-of-range Celsius readings cannot acquire freshness.
No runtime scheduling/actuator decisions consume this new field yet. No temperature
freshness policy, automatic start/stop or receipt-only acceptance is enabled by
this change; cycle ownership and qualified transport remain outstanding.

This is independent of the offline scheduling foundation in PR #408. The two
milestones establish explicit schedule and evidence contracts before runtime
integration. Remaining work includes source/role qualification, comfort and
observed-cycle semantics, bounded persistent trigger/stop/restart ownership,
manual/away/hygiene/fuse/peak precedence, and measured residual load integration.

Transport policy: prefer local REST when enabled for the installation. With EW
configured as `heat_pump.enabled: true`, `heat_pump.driver: nibe_local`, only the
local driver is selected, even if cloud entity mappings/credentials also exist.
Missing readings or receipt-only timestamps do not trigger cloud fallback.
Timestamp quality and transport preference are separate: a future local scheduler
must explicitly define its receipt-age policy rather than replacing local readings
with myUplink data merely to obtain source timestamps. No automatic device discovery
or transport/configuration switching is introduced here.
