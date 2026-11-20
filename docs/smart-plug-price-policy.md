# Nonessential smart-plug price policy (#217 milestone)

Disabled unless explicitly configured in `house_config.yaml`. Only enroll devices
that may safely lose power and restart unattended. Never enroll refrigerators,
medical equipment, networking, pumps, heating safety systems, computers with
unsaved work, or any other essential device. EW does not classify devices for you.
Keep existing Home Assistant automations from controlling the same enrolled plugs.

```yaml
smart_plugs:
  enabled: false # change to true only after reviewing each device
  devices:
    - switch: switch.nonessential_display
      enabled: true
      nonessential: true
      always_on: false
      off_above: 2.0
      restore_below: 1.0
      min_on_minutes: 15
      min_off_minutes: 15
      # presence: binary_sensor.office_occupancy  # optional, on = someone is there
      # unoccupied_minutes: 15                    # log after the room stays empty this long
```

Thresholds use the configured contract's complete import-price calculation, in
its currency per kWh, including configured fixed/tariff components. Values above
are examples, not recommended thresholds. Restore must be strictly below off;
dwell is 5–1440 minutes, default 15. There are at most 32 explicitly enrolled
switches. Duplicate targets and invalid thresholds disable this policy with a log
message; other house controls keep running. `always_on: true`, missing explicit
nonessential consent, or missing device enablement excludes a device.

Each minute the policy uses the current price interval, never yesterday's fallback
profile. Missing/nonfinite prices cause no switching. It reads each enrolled
switch freshly from HA and waits a complete minimum-on dwell after first seeing
it on. High price switches it off only after that dwell. Low price restores only
an off state whose context matches the changed state returned by EW's own service
call, after minimum-off dwell. Initially off devices are never switched on.

The adapter uses HA's documented [state and action REST API](https://developers.home-assistant.io/docs/api/rest/).
Service success alone is insufficient: the response must contain that switch's
expected changed state and a new context. Missing context, ambiguous/failed writes,
lost state, changed context (including conservative suspension for attribute-only
updates) or observed manual changes suspend the device until restart. There are
no automatic retries. Logs show observed transitions and suspension. Integrations
without synchronous changed-state evidence cannot provide automatic restoration.

Ownership is process-local. Restart or shadow mode clears it; a plug left off then
needs manual restoration. Disablement does not force devices on. Manual activity
that HA does not expose as a state/context change cannot be detected; observation
and a service call are not atomic. This needs installation qualification before
enabling, and is not a hardware safety controller. Shadow mode sends no plug calls.

This is a price-policy milestone, not the complete #217 feature. It does not learn
standby power, switch a plug off because a room is empty or the house is away,
calculate savings, coordinate fuse/phase restoration budgets, or provide
setup/status dashboard controls. No runtime device has been tested or enrolled
by this change.

## Presence and away (notes only)

Optional `presence` on an enrolled plug is `binary_sensor.<name>` or
`input_boolean.<name>`. `on` means the room is occupied. `off` means empty.
`unavailable`, `unknown`, a missing read and any other value are not empty:
that wait restarts. While the switch stays `on` and the room stays empty for
`unoccupied_minutes` (default 15, range 5–1440), one log line names the plug.
The wait starts again when the room is occupied or the plug is off. An invalid
presence id is ignored and does not disable the price policy.

While system away mode is on, an enrolled plug that is `on` is logged once.
Presence is not counted during away. The next away period can log again.
Neither note calls `switch.turn_on` or `switch.turn_off`. The price policy is
unchanged. A failed log does not change the relay. Restart clears the notes.
