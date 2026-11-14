# Hot-water deadline planning — offline foundation

`scripts/propose_hot_water.py request.json` selects a contiguous fixed-electrical-
power heating window before an explicit deadline. It is local and offline: no
runtime settings, actuator commands, temperature rules or shadow settings change.
`control_ready` is always false. This is the first scheduling-contract milestone,
not a replacement for the running Zenai hot-water controller.

Input example (full import prices, including applicable fees/taxes, in one currency
per kWh; electrical input kW, not heat output or a guessed COP):

```json
{
  "request": {
    "now": "2026-11-14T00:00:00+01:00",
    "earliest": "2026-11-14T00:00:00+01:00",
    "deadline": "2026-11-14T01:00:00+01:00",
    "duration_min": 30,
    "electrical_power_kw": 2
  },
  "prices": [
    {"t": "2026-11-14T00:00:00+01:00", "buy": 2},
    {"t": "2026-11-14T00:15:00+01:00", "buy": 1},
    {"t": "2026-11-14T00:30:00+01:00", "buy": 1},
    {"t": "2026-11-14T00:45:00+01:00", "buy": 3}
  ]
}
```

All times require offsets and are compared in UTC, including repeated DST hours.
Price quarters must be unique and aligned. No missing-price forward filling is
allowed. A caller-supplied `permitted: false` rejects windows touching that quarter;
this does not calculate fuse headroom or certify a guard. Search includes partial
quarters and windows whose end touches a price boundary. Ties choose the earliest
start. Maximum horizon is 36 hours and heating duration six hours. Missing complete
coverage or an impossible deadline returns `unavailable`, never an immediate write.

Output includes fractional-quarter average `hot_water_kw` reservations conserving
the specified electrical energy and an estimated import-only cost. This cost is
not battery/PV opportunity cost, realized savings or a joint optimum.

Optional `forecast` rows (`t`, `load_kw`, plus existing battery optimizer fields)
require `baseline_contract: "hot_water_excluded"`. The caller must establish that
the forecast excludes this hot-water load using measured signal reconstruction
as described in [load forecast evaluation](load-forecast-evaluation.md).
`reserve_load` returns copies with the reservation added to `load_kw`, preserves
solar/EV fields, rejects repeated application and requires full forecast coverage.
It is suitable for explicit pure-optimizer comparison, not automatically wired
into `plan_from_db`: EW's existing household baseline may already include hot water.

Before runtime integration: establish source-dated tank temperatures and electrical
power; define comfort/deadline and observed-cycle semantics; preserve away/manual,
hygiene, fuse and peak precedence; persist bounded active-cycle ownership and stop/
restart behavior; qualify the chosen device trigger/release transport; then publish
one idempotent reservation against a measured residual baseline. Current Zenai
temperature/trigger parameter IDs and tank/COP assumptions are not copied as EW
defaults. Live control qualification remains separate from these replay tests.
