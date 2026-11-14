# Runtime hot-water shadow monitor — #407

The engine can now run the advisory demand/price proposal in a separate worker.
It is **disabled by default**. This is a monitor, not a timed-boost controller:
it never calls a heater driver, sends commands, acknowledges simulated cycles,
changes GPM decisions or applies a reservation to the battery plan.

When explicitly configured, the existing GPM evaluation submits its already-read
temperature observation and manual/away/hygiene flags. No extra heater, HA or cloud
read is made. Enabled local REST remains the selected preferred transport; missing
or receipt-only local evidence never triggers cloud fallback. Receipt acceptance
and sensor-role qualification must be explicit.

The worker requires global shadow mode. It suspends proposals outside shadow,
under manual/away/hygiene precedence, for unsupported drivers or unqualified sensor
roles. The existing critical-temperature/hygiene control path is unchanged.
Price-only proposals do not establish future fuse/peak headroom; every status has
`guard_qualified: false`, `control_ready: false`, `reservation_applied: false`.

Configuration shape (policy values here are synthetic, not heater recommendations):

```yaml
heat_pump:
  enabled: true
  driver: nibe_local
  # Keep the installation's existing connection/point/control settings.
  hot_water_shadow:
    enabled: false
    temperature_role_verified: false
    comfort_policy:
      comfort_c: 50
      target_c: 55
      max_trigger_age_s: 7200
      min_trigger_interval_s: 3600
      comfort_window_s: 1800
      comfort_bypasses_interval: true
      duration_min: 15
      electrical_power_kw: 2
      max_age_s: 90
      allow_receipt: true
```

No installation configuration is changed by this PR. To opt in later, qualify
the actual temperature role and policy first and keep global shadow on. Existing
device-control opt-ins are not changed or inferred from monitor configuration.

The bounded queue holds one waiting sample and replaces it with the latest one.
Only one daemon worker is created. Disabled configurations start no worker. A slow
database, disk or publisher does not make `submit` wait for that I/O. Failures are
sanitized into unavailable status; raw exceptions, endpoints and credentials are
not included. The worker only copies allowlisted observation/policy fields.

Demand anchors persist atomically through existing private `ew_settings` storage
under `hot_water_shadow_demand`, before any advisory proposal is published. The
monitor does not invent accepted trigger history from temperatures or simulated
acknowledgements. Missing-history anchors persist across evaluator/process restart;
changed policies require an explicitly managed new qualification scenario. State
or price failures do not produce a proposal or reset the fixed deadline.

Prices come from stored `elpriser` start/end intervals, with configured full import
costs. Fully covered physical UTC quarters are duration-weighted; overlapping
intervals are refused. Missing quarters are omitted, never forward-filled, copied
from yesterday or fetched from an external service. Selection still requires a
complete permitted price window.

Sanitized status is published to the existing `overrides` table as
`hot_water_shadow_status`. `decode` rejects malformed, future or older-than-90s
reports. Publication failure therefore becomes unknown, not permanently healthy.
This PR supplies the status plumbing, not a user-facing card/API. A later owner
status view must use this decoder rather than treating an old raw row as current.

Remaining work: owner UI/API, qualified real timed-boost/release and reconciliation,
actual runtime comfort/cycle behavior and measured residual-baseline integration.
The live installation, physical heater and actual energy delivery were not tested
or changed; PostgreSQL and persistence checks use isolated synthetic data.
