# Dedicated hot-water electrical-load evidence — #407

EW can optionally capture a dedicated hot-water electrical-power reading in its
existing minute log. This prepares measured residual-load qualification before
adding future hot-water reservations to the battery forecast. No forecast model,
GPM decision, heater control, shadow setting or live mapping is changed.

With no explicit mapping, all four new nullable `sensor_log` fields stay unknown:

| Field | Meaning |
|---|---|
| `hot_water_power_w` | Nonnegative dedicated electrical input watts; a measured zero stays zero. |
| `hot_water_power_sample_at` | UTC epoch seconds from the reported source/receipt timestamp, or NULL. |
| `hot_water_power_basis` | `ha_report`, `local_receipt`, `unknown`, or NULL when unavailable. |
| `hot_water_power_source` | Code-owned `ha_sensor` or `nibe_local`, never entity IDs/endpoints. |

The existing startup migration adds the nullable columns idempotently. It does not
rewrite old readings, replace missing values with zero or backfill source dates.
Minute-row insertion time is separate from the original power timestamp.

## Explicit cached HA meter

For a non-local-REST heat-pump route, configure an actual dedicated sensor:

```yaml
heat_pump:
  # Preserve the existing enabled/driver/control configuration.
  hot_water_meter:
    entity_id: sensor.hot_water_electrical_power
    boundary: hot_water_electrical
```

The placeholder sensor must already exist in HA. Its metadata must declare
`device_class: power` and `unit_of_measurement: W` or `kW`. Negative, unavailable,
boolean and nonfinite readings stay unknown. The collector reads only EW's existing
HA state cache; it makes no extra HA/device request. `last_reported`, falling back
to `last_updated`, is preserved across repeated reads. Missing or naive dates leave
the value undated; cache-read time is never substituted.

## Preferred local REST route

When `heat_pump.driver: nibe_local` is selected, it remains exclusive: missing local
power does not fall back to an HA sensor. The local driver can read an explicitly
qualified `points.hot_water_power_w` binding with an exact register/type/ID/unit
identity and `boundary: hot_water_electrical`. Both W and kW bindings are normalized
to watts; no register preset or title-based mapping is supplied. Other driver
readings and write capabilities are unchanged.

The local value uses existing `_received_at`, labelled `local_receipt`. This is
not a device measurement clock or freshness guarantee. The collector never
substitutes compressor/whole-system power, heat output, a COP/tank estimate or
operating-mode inference for a dedicated hot-water electrical measurement.

An explicit boundary declaration is an operator input, not independent physical
qualification. Validate the sensor's actual electrical boundary and source ages
before using it to exclude demand from a baseline. Current runtime forecasts do
not consume these new columns. The [offline residual reconstruction](hot-water-residual-load.md)
requires separately captured grid/PV/battery source dates, aligns the signals,
rejects stale/inconsistent evidence and prevents repeated hot-water exclusion.
Old unmetered/undated history remains unqualified.

All capture is read-only and optional. No installation configuration is enabled
or modified by this change, and no physical meter/heater qualification is claimed.
