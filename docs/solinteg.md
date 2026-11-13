# Solinteg via Home Assistant (#219)

EW can map the Solinteg plugin in `wills106/homeassistant-solax-modbus` to the
existing generic battery driver. Source contract reviewed at
[`0c715ee6ebb989c1331a6f4513657313df1b9fcf`](https://github.com/wills106/homeassistant-solax-modbus/blob/0c715ee6ebb989c1331a6f4513657313df1b9fcf/custom_components/solax_modbus/plugin_solinteg.py).
The [original support discussion](https://github.com/wills106/homeassistant-solax-modbus/discussions/1144)
describes model coverage; it is not a guarantee for every firmware/model.

Scan Home Assistant and review the battery suggestion. The exact battery-power
sensor is normalized to EW's positive-charging convention. The generated YAML
contains `power_invert: true` and defaults to **`control: samarbete`**. A sensor
without the complete control contract remains monitoring-only.

Control is offered only when the same device exposes Working Mode with both
`General` and `EMS BattCtrl`, plus the signed battery charge/discharge target
in W or kW. EW writes the requested target **before** selecting EMS mode, uses
negative values for charging and positive for discharging, and checks current
entity units and signed bounds before writing. Hold requests a zero target;
auto selects General. An unknown unit/range or failed target write does not
select EMS mode. No unsupported idle/export-limit intent is fabricated.

The integration's source supplies SOC, signed power and the mode/target
definitions. EW's bundled Solinteg FTW driver independently documents the same
target sign. No upstream code was imported or executed and no new Modbus
registers or protocol implementation are added here.

Review the actual HA entities, inverter/BMS limits, SOC reserve and command
behavior before explicitly changing `control` to `styr`. Device firmware,
disconnect behavior and hardware operation have not been qualified by this
change. Existing FTW control gates are unchanged. `tests/test_solinteg_battery.py`
covers discovery through YAML, units/signs, missing capabilities, target bounds,
write ordering/failure and General-mode release with an isolated HA boundary.
