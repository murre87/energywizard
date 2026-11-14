# NIBE hot-water binding audit — #407

Before implementing real timed boosts, audit the exact local REST points and
explicit installation bindings:

```text
python scripts/audit_nibe_hot_water.py private-capture.json
```

This tool is offline and read-only. It reads only that local JSON, never constructs
a device client, makes a network request, writes a setting or changes EW configuration.
It does not select cloud fallback. Enabled local REST remains the preferred transport;
its mappings must be qualified rather than replaced with guessed cloud parameter IDs.

Input has `points` (the captured local point dictionary) and `bindings` with these
semantic roles:

| Role | Required evidence |
|---|---|
| `boost` | Explicit command point identity, writable holding register, divisor 1, native allowed values, distinct start/release values and declared bounds. |
| `demand_mode` | Explicit command point identity, writable holding register, divisor 1, allowed values and requested/release values within declared bounds. |
| `top_temperature` | Explicit unique point identity, valid Celsius value. |
| `charging_temperature` | Separate explicit unique point identity, valid Celsius value. |
| `electrical_power` | Explicit unique point identity, nonnegative W or kW, with `boundary: "hot_water_electrical"`. |

Every binding requires `variable_id`, `register`, `register_type` and `unit` matching
returned metadata exactly. No default IDs or title-only mappings are supplied.
Command bindings additionally require `allowed_values` and `release_value`, plus
`start_value` for boost or `requested_value` for demand mode. Allowed values must
fit declared bounds and native word width, avoid unavailable sentinels, and include
the current state. Unknown/contradictory metadata stays blocked. Duplicate point or
register identities across roles are refused.

Capture IDs, register addresses and cloud parameter IDs are distinct. Do not copy
test fixture values into installation configuration: all fixture IDs are deliberately
synthetic. These bindings belong to this audit input, not new runtime write keys in
`heat_pump.points`; existing driver write capabilities are unchanged.

Reports contain only code-owned role/reason labels, numeric point/register identity
and current numeric values with validated units. Raw titles, point bodies, endpoints and credentials are
excluded. Input is limited to 2 MB/10,000 points. Keep captures private even though
the report does not dump their extra fields.

`metadata_consistent` means only that the supplied mapping matches the supplied
capture. It does not verify that the device identity or capture is authentic, that
an enum has the intended semantics, that a power point measures only hot water,
that data is fresh, or that a timed boost/release physically works. Boundary and
semantic declarations remain installation evidence requirements. Every report
keeps `control_ready`, `physical_verified`, `release_verified`, `timing_verified`
and `freshness_verified` false, even when all metadata checks pass.

Next commissioning evidence must cover: exact model/firmware and certificate identity;
verified temperature/power boundaries; bounded boost duration and overwrite/restart
semantics; independent active-state/readback; release behavior; ambiguous delivery;
and one physical writer with manual/away/hygiene precedence. Real writes require
separate explicit commissioning authorization. Passing this audit never enables them.

The existing advisory monitor and owner card remain disabled by default and do not
call this tool automatically. An installation using `generic_climate` does not gain
native NIBE control merely because this audit is available.
