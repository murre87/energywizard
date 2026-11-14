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
```

Both total active-power sensors must belong to the same Home Assistant device,
have units W or kW, and be unambiguous. Phase currents in A are optional and
are used by existing fuse protection. Review the generated mapping before
applying it; renamed entities can be mapped manually with the same keys.

Net grid power is total active import minus total active export, positive when
buying electricity. Per-phase active power and reactive power are not substituted
for these totals. This does not change live configuration automatically.
