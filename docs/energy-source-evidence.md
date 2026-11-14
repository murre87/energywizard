# Optional raw AC source-evidence capture — #407

The ordinary house balance can contain rolling grid averages, corrected PV floors
and conservative missing-data substitutions. Those values must not acquire source
timestamps and become raw measurements for residual-load qualification.

This separate optional capture uses explicit active-power HA cache mappings and
the dedicated hot-water evidence already read by EW. It makes no extra HA, heater
or cloud requests and changes no control, display balance or runtime forecast.
It is disabled by default and does not enable an installation mapping automatically.

Example shape (replace placeholders only after boundary/sign qualification):

```yaml
energy_source_evidence:
  enabled: false
  boundary: ac_household
  grid:
    entity_id: sensor.grid_active_power
    positive: import
  pv:
    entity_id: sensor.pv_ac_power
  battery:
    entity_id: sensor.battery_ac_power
    positive: charge
```

Each cache sensor requires `device_class: power` and W/kW units. Grid `positive`
must explicitly be `import` or `export`; battery must be `charge` or `discharge`.
Output normalizes import/charge positive. PV is nonnegative generation; missing
or negative PV is not replaced by an inferred export floor. No U×I apparent-power
estimate, aggregation or fallback list is used. Duplicate meter IDs across roles
are refused. AC boundary/sign declarations are operator assertions, not physical proof.

Hot-water evidence comes from the existing [dedicated meter capture](hot-water-power-evidence.md).
Selected local REST stays exclusive and retains `local_receipt` timing; an HA
meter is not substituted when its local value is unavailable. Whole compressor/
system power and thermal estimates are never used as dedicated hot-water watts.

The existing minute log gains one nullable `energy_source_evidence` JSONB column
through an additive idempotent migration. Disabled capture stores SQL NULL. Enabled
snapshots contain only normalized powers, original source dates/bases, capture time,
an opaque mapping/process fingerprint and `physical_verified: false`. Raw entity
IDs, endpoints and credentials are excluded by a strict log-field allowlist.
Unknown readings stay null; source time is never replaced with capture/log time.

The fingerprint changes when source mappings/signs or the capture process change.
Residual reconstruction rejects intervals across different/missing fingerprints,
in addition to age, skew and gap checks. It is a context discriminator, not device
authentication or a guarantee that clocks/measurement boundaries are qualified.

Export a bounded local recording using the existing database environment settings:

```text
python scripts/export_energy_source_evidence.py --since 2026-11-14T10:00:00+00:00 --until 2026-11-14T10:15:00+00:00 > private-recording.json
python scripts/reconstruct_hot_water_load.py private-recording.json
```

Both observation endpoints are included so the final sample can bound the last
interval. Export requires explicit offset-aware dates, at most 31 physical days and
100,000 rows. It uses a fresh read-only SQL transaction with a statement timeout;
oversized results are refused instead of silently truncated. Invalid date/range
arguments are checked before opening a database connection.

Only the source-evidence column and observation timestamps are read. Missing or
invalid snapshots remain explicit gap markers, not removed rows or zero values.
Old logs do not acquire invented source dates. Export output is directly compatible
with the [offline residual validator](hot-water-residual-load.md), which keeps
`adoption_ready: false`. Receipt evidence still requires its explicit offline flag.

Existing sensor-log retention/downsampling remains unchanged. Sparse old logs may
fail coverage/gap requirements and must not be held across a quarter to fabricate
coverage. Real AC-boundary/meter validation, source quality, chronological economic
evaluation, runtime adoption and physical heater-control qualification remain pending.
