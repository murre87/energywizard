# NIBE local REST driver

This implementation primarily targets the NIBE S1255. It has not been verified
against other heaters. The S1155 read preset follows the published register map,
but is not hardware-validated; no compatibility with other models is claimed.

`heat_pump.driver: nibe_local` connects directly to the heater over HTTPS (normally
8443), using Basic authentication and a required SHA-256 certificate pin. Enable
local REST in installer menu 7.5.15. This driver uses standard Python libraries and
does not require myUplink credentials or automatically fall back to the cloud.

## What is implemented

- Discover the selected `deviceIndex` from the actual top-level `devices` array.
  Device index, local variable ID, Modbus register address and cloud parameter ID
  are distinct identifiers. A serial number is not assumed to be the device index.
- Read the device's point dictionary and check matching metadata/value identities,
  integer types, sentinels, units and declared divisor before returning a value.
- For discovered S1155/S1255 products, use NIBE's documented input register map:
  outdoor 1, supply 5, return 7, hot-water top 8, room 26 and compressor state 1100.
  Match the returned register type/address, not a guessed local variable ID. Missing
  sensors stay unknown. Other models require explicit bindings; no shared map is assumed.
- Support configured room target, water start/stop, heating-season threshold and
  operating-mode writes. No write bindings or operating-mode values are supplied
  automatically. Every real write reads current metadata, validates writability,
  units, integer representation, device bounds and installation limits, then PATCHes
  the device's documented datavalue-array format and independently reads back.
- Require both per-point `modified` status and matching readback before reporting a
  new write as successful. When both water thresholds are configured, reject a new
  start at/above the current stop or a stop at/below the current start.
- Keep writes disabled by default and respect shadow mode. Reapplying a confirmed
  absolute target sends no PATCH. An unconfirmed command blocks further real writes
  in that driver instance until an independent read confirms it; no blind replay.

Pin validation happens on the connected socket before any HTTP request or credentials
are sent. A missing/malformed pin prevents authenticated access. Redirects are rejected.
Response size and read duration are bounded, and connections close after each request.
Errors do not print credentials, headers or raw device response bodies.

Local values may lack a source timestamp. `_received_at` is the local receipt time,
explicitly labelled `_timestamp_basis: local_receipt`; it does not prove when the
sensor sampled. Total system electrical power must not be labelled compressor-only
power. `compressor_power_kw` stays unknown unless explicitly configured to a verified
compressor-specific kW point.

## Configuration

In the runtime environment (not committed):

```dotenv
NIBE_LOCAL_USERNAME=your-local-api-user
NIBE_LOCAL_PASSWORD=your-local-api-password
NIBE_LOCAL_TLS_PIN_SHA256=your-heaters-64-hex-sha256-fingerprint
```

Colons/spaces in the fingerprint are accepted. Compare it with the trusted value
shown by the heater. Optional `NIBE_LOCAL_HOST`/`NIBE_LOCAL_PORT` retain their previous
meaning; YAML connection values take precedence. The full `docker-compose.yml`
passes these optional environment variables to smartbox. Other launch methods need
equivalent environment injection.

As a Home Assistant add-on: fill in `nibe_local_username`, `nibe_local_password` and
`nibe_local_tls_pin_sha256` under the add-on's Configuration tab and restart it. Missing values
are reported once in the add-on log (without the values themselves).

Start with a read-only configuration:

```yaml
heat_pump:
  enabled: true
  driver: nibe_local
  control_enabled: false
  connection:
    host: 192.0.2.10
    port: 8443
    device_index: 0
    expected_product: "NIBE S1255" # replace with the exact discovered product name
    timeout_s: 5
```

`expected_serial` is an optional additional identity check. Writes require an exact
`expected_product` or `expected_serial` match as well as `control_enabled: true`.

Some S1255 units report an empty `product.name` from `/api/v1/devices` (#145). The
S1155/S1255 read preset is then not selected automatically: set `model: "S1255"`
under `connection` to choose it, and use `expected_serial` (not `expected_product`,
which cannot match an empty name) to pin the device identity. The driver prints a
one-time hint when the name is empty. The preset registers (outdoor 1, supply 5,
return 7, hot-water top 8, room 26, compressor 1100) were confirmed against a real
S1255 in #145.

Failed requests log the exception type once per change (for example
`OSError errno 9`), never credentials, headers or response bodies.

The optional `points` mapping accepts read keys from the driver contract
(`indoor_temp`, `outdoor_temp`, `forward_temp`, `return_temp`, `water_temp`,
`degree_minutes`, `compressor_running`, `compressor_power_kw`, `operating_mode`)
and write keys `room_target`, `water_start`, `water_stop`, `heating_start`.
Each binding identifies:

| Binding field | Meaning |
| --- | --- |
| `register` | Exact integer Modbus address from the local point metadata |
| `register_type` | `MODBUS_INPUT_REGISTER` (read default) or `MODBUS_HOLDING_REGISTER` |
| `variable_id` | Optional additional exact local variable identity |
| `unit` | Exact metadata unit; temperature writes require `°C` |
| `limits` | Required `[minimum, maximum]` for temperature writes, in degrees |
| `allowed_values` | Required explicit native enum list for mode writes |

Use `mode_values` to map caller intents to verified native values. The current engine
still has legacy numeric operating-mode intents; these are not automatically interpreted
as NIBE codes. Configure their meanings only after reviewing the actual calling rules.
No mapping means mode requests return false. Read mode values are translated back only
when the configured mapping has a unique inverse.

Do not use a point merely because it is writable. A hot-water profile threshold is
not necessarily the threshold currently controlling the heater; changing a high-profile
threshold does not activate that profile or prove charging starts. A curve offset is
not a room temperature, and an installation without the appropriate room sensor may
not expose a usable room target. Match each binding to the exact intended behavior.

## Scope and verification limits

This addition supplies transport, validated readings and explicit absolute-setting
writes. It does not add temporary-boost scheduling, AUX-based heating blocks, timed
pause, curve-offset control, hygiene-cycle scheduling or a cloud replay path. Those
require their own lifecycle and recovery design. No installation-specific controls,
identifiers, credentials or private source paths are included.

REST readback can lag actual applied settings on some points. Such points cannot be
treated as verified solely because a PATCH was accepted, and should not be bound here
without an appropriate independent readback strategy. The driver's pending latch is
in memory, not a persisted timed-action journal; no timed action is implemented.

The existing main loop handles water target updates as a pair and records a target
without checking both setter results. This PR does not redesign that loop. Commission
the intended bindings and confirm physical operation before enabling automated control.
Unconfirmed writes are surfaced as false; this is not a guarantee of automatic recovery.

The local discovery, point shape and PATCH contract have device-hosted documentation
and separately recorded S1255 observations behind them. This EnergyWizard implementation
has only offline tests: synthetic device metadata, fake TLS connections, pin-before-auth,
scaling/sentinels, device identity, writable/range checks, shadow mode and uncertain
delivery/readback. No heater, production optimizer or authenticated cloud service was
contacted to implement or test this branch. Physical writes and firmware compatibility
still require commissioning on each installation.

Public references:

- [NIBE technical guide, January 2026](https://headless.nibe.eu/download/18.4e8833a719b52e0331e3da/1768300199729/M12676SV%20%282026-01-13%29.pdf)
- [NIBE firmware release notes](https://www.nibe.eu/webdav/files/myuplink_changelog/nibe-n.pdf)
- Device-hosted `GET /` documents its own local REST API and PATCH schema; inspect it
  on the installation when separately authorized. No unverified universal write map
  is inferred from the public release notes.
