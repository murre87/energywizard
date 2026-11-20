# Nonessential smart-plug price policy (#217 milestone)

Disabled unless explicitly configured in `house_config.yaml`. Only enroll devices
that may safely lose power and restart unattended. Never enroll refrigerators,
medical equipment, networking, pumps, heating safety systems, computers with
unsaved work, or any other essential device. EW does not classify devices for you.
Keep existing Home Assistant automations from controlling the same enrolled plugs.

```yaml
smart_plugs:
  enabled: false # change to true only after reviewing each device
  # home: person.someone                 # on/home means someone is home
  # away_minutes: 15
  # vacation: input_boolean.vacation     # on means vacation
  devices:
    - switch: switch.nonessential_display
      enabled: true
      nonessential: true
      always_on: false
      off_above: 2.0
      restore_below: 1.0
      min_on_minutes: 15
      min_off_minutes: 15
      # occupied: binary_sensor.office   # on/home means the room is in use
      # unoccupied_minutes: 15
      # away: false                      # follow the house home signal
      # vacation: false                  # follow the vacation signal
      # presence_off: false              # true switches the relay off
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

Optional `occupied`, `home` and `vacation` add a log line. They switch a relay
only when that plug sets `presence_off: true`. `occupied` is per plug
(`binary_sensor`, `input_boolean`, `device_tracker` or `person`). `on` or
`home` means someone is there. `off` or `not_home` starts `unoccupied_minutes`
(default 15, range 5–1440). `home` is the same signal for the whole house, with
`away_minutes`. `vacation` is a `binary_sensor` or `input_boolean` that is `on`
during vacation and logs once while it stays on. Unknown, unavailable or a
missing reading is not empty and is not vacation. The note is repeated only
after the signal returns and the wait passes again. The timers are process-local
and restart clears them.

`presence_off: true` switches that plug off after an opted-in signal has
finished its wait and the minimum-on dwell has also elapsed. The room follows
`occupied`. `away: true` follows the house `home` signal. `vacation: true`
follows `vacation`. At least one of those is required. A missing or non-finite
price still causes no switching. The write uses the same changed-state check as
the price policy. One failed or ambiguous write suspends the device; there is
no retry. The plug is not turned back on when the room is occupied again,
someone comes home, vacation ends, or the price falls. Turning it on by hand
suspends the device until restart. An off caused only by a high price is still
restored when the price falls, unless presence still wants that plug off.
Shadow mode sends no plug calls.

Invalid occupancy settings disable the notes and this switch, and leave the
price policy running.

This is a price-policy milestone, not the complete #217 feature. It does not
learn standby power, turn a plug back on when someone returns, calculate
savings, coordinate fuse/phase restoration budgets, or provide setup/status
dashboard controls. No runtime device has been tested or enrolled by this change.
