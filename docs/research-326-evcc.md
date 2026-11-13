# evcc evaluation — #326

Reviewed 2026-11-13: evcc commit
[`922d3874a859aff9f11e049941a599919b150908`](https://github.com/evcc-io/evcc/tree/922d3874a859aff9f11e049941a599919b150908),
against EnergyWizard `00f4d51`. This completes the research recommendation;
no upstream code, dependency, service or device configuration was adopted.

## Recommendation

**Integrate only in a narrow, optional way if an existing evcc installation
provides a demonstrated missing capability.** The first experiment should be
read-only observation of an independently operated evcc instance. Do not replace
GPM, the battery planner, HA drivers or the existing fuse/control safeguards.
There is no measured user benefit yet that justifies mandatory adoption.

## Fit and boundaries

| Area | Evidence | Consequence for EnergyWizard |
| --- | --- | --- |
| Chargers | Go interfaces separate status, enable/current control and optional phase/power capabilities. | Useful capability design; these are in-process Go interfaces, not a drop-in Python provider API. |
| HA | Concrete charger and meter implementations already use HA entities/services. | Another HA wrapper mostly duplicates our existing boundary. |
| Solar/batteries | Meter, SOC and optional battery-mode capabilities are separate. | A supported meter does not establish arbitrary inverter charge/discharge control. |
| Modbus | The Solis RHI hybrid template reads grid/PV/battery registers over RS485. | Match model, transport, registers and signs explicitly; that template is not proof of S6 TCP control compatibility. |
| Heating | Device templates include heat-pump/heater examples. | Verify the selected model and semantics; this does not establish parity with our heat-pump modes, hot water and safety logic. |
| HTTP API | State reads coexist with loadpoint mode, current, phase and planning setters. | A setter changes evcc policy; it is not necessarily a raw device command. Running both controllers would require explicit exclusive ownership. |

Sources: [interfaces](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/api/api.go),
[HA charger](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/charger/homeassistant.go),
[HA meter](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/meter/homeassistant.go),
[Solis template](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/templates/definition/meter/solis-hybrid.yaml),
[heating example](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/templates/definition/charger/demo-heatpump.yaml),
[HTTP routes](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/server/http.go).
Local boundaries: `smartbox/drivers/charger.py`, `drivers/charger_easee.py`,
`drivers/battery.py`, `gpm.py` and `battery_control.py`.

## Licensing and operational cost

The root [LICENSE](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/LICENSE)
is MIT, but [exclusions](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/LICENSES/exclusions.md)
explicitly separate sponsor-required components and their per-instance terms.
[Dependency notices](https://github.com/evcc-io/evcc/blob/922d3874a859aff9f11e049941a599919b150908/LICENSES/dependencies.md)
are additional evidence, not a complete distribution review. Do not label the
whole distribution MIT-only or assume a sidecar exempts it from its terms.
Any code import or bundled binary needs a component-specific license/notice
review. This research copies no code and makes no blanket compatibility ruling.

A sidecar adds releases, API/schema compatibility, credentials, polling and
failure handling. HA/device calls remain owned by one controller. Unavailable
or stale sidecar data must not become zero consumption or block a control tick.

## Bounded next experiment

Estimate: 1–2 days for a read-only prototype and contract tests, excluding
installation validation. Use only `GET /api/state`; validate identity, units,
finite values, observation age and missing fields. Restrict access through the
chosen deployment boundary; do not assume a configured credential is read-only.
No setters, automatic discovery writes or remote command forwarding.

Acceptance: fixtures for schema changes, timeouts, stale/future observations,
unknown versus zero power and both grid signs; prove zero outgoing writes.
Proceed beyond observation only after one real capability gap and exclusive
device ownership are demonstrated. A driver-only service would be a separate
design/qualification effort, not a small wrapper around evcc's control API.
