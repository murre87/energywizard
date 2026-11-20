# Smart-plug presence notes (#217)

Optional and separate from the [price policy](smart-plug-price-policy.md). This
step only writes a log line. It never calls `switch.turn_on` or `switch.turn_off`,
whether or not shadow mode is on.

```yaml
smart_plugs:
  presence:
    away: person.emil                  # home = someone is home
    vacation: input_boolean.semester   # on = vacation
    away_minutes: 15
    vacation_minutes: 15
    devices:
      - switch: switch.office_screen
        occupancy: binary_sensor.office   # on = someone is in the room
        unoccupied_minutes: 15
        away: true
        vacation: true
```

`away` may be a `person`, `device_tracker`, `binary_sensor` or `input_boolean`.
For the first two, `home` means someone is home and any other zone means away.
For the last two, `on` means someone is home. `vacation` is only a
`binary_sensor` or `input_boolean`, and `on` means vacation. `occupancy` uses
the same reading as `away`: `on` or `home` means the room is occupied.

Each signal has to stay in its new state for its own dwell (5–1440 minutes,
default 15) before one line is logged: `presence would turn off (room empty,
house away, vacation)`. When every opted-in signal has been clear for its
dwell, one line says `presence would turn on`. A missing, `unknown` or
`unavailable` reading is not treated as empty, and it also blocks the "would
turn on" line. A failed log is tried again on the next pass. At most 32
switches. A device with no room, away or vacation flag is rejected and this
note is disabled; the price policy keeps its own switch.

No relay has been operated by this change, and no installation has been enrolled.
