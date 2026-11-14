# ESPHome P1 meter

EnergyWizard's installation discovery recognizes the standard entity names from
[esphome-p1reader](https://github.com/psvanstrom/esphome-p1reader/blob/main/p1reader.yaml),
including names with a device prefix:

```yaml
power_meter:
  driver: power_w
  entities:
    import_w: sensor.momentary_active_import
    export_w: sensor.momentary_active_export
    current_l1: sensor.current_phase_1
    current_l2: sensor.current_phase_2
    current_l3: sensor.current_phase_3
    import_l1_w: sensor.momentary_active_import_phase_1
    export_l1_w: sensor.momentary_active_export_phase_1
    import_l2_w: sensor.momentary_active_import_phase_2
    export_l2_w: sensor.momentary_active_export_phase_2
    import_l3_w: sensor.momentary_active_import_phase_3
    export_l3_w: sensor.momentary_active_export_phase_3
```

Discovered active-power sensors must belong to the same Home Assistant device,
have units W or kW, and be unambiguous. Phase currents in A are optional and
are used by existing fuse protection. Review the generated mapping before
applying it; renamed entities can be mapped manually with the same keys.

Net grid power is total active import minus total active export, positive when
buying electricity. Configured totals retain priority over the phase sum, and
phase values are not added to totals. If no total-power mapping is configured,
all six phase import/export measurements must be available to calculate net
power. An incomplete/unavailable phase means no calculated total, never zero.

The meter reader additionally returns signed `l1_w`, `l2_w`, `l3_w` for configured
phase pairs; an unavailable pair is `None`. These values are not used to estimate
phase currents or replace the existing current-based fuse guard, and are not
separate dashboard history series. Reactive/apparent power is not used as active
power. This does not change live configuration automatically.
