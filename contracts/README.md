# Kontrakt mellan EnergyWizards delar

Det som passerar gränsen mellan Core och planeringen (och senare drivrutinerna) är en ren JSON-struktur med ett versionerat schema. Det är
det som gör att en del kan flyttas till en egen process eller ett eget repo utan att något tappas tyst.

| Schema | Riktning | I dag skapas det av |
| --- | --- | --- |
| `planner-decision.schema.json` | planering -> Core | `gpm.GlobalPriorityManager.evaluate` |
| `ev-plan.schema.json` | planering -> Core | `decisions.calculate_ev_charge_plan` |

## Regler

- **Facit är de riktiga besluten.** `tests/test_contracts.py` kör 2 600 beslut (gpm:s golden-scenarier) och en riktig laddplan mot schemat.
- **Strängt:** `additionalProperties: false`. En ny nyckel i ett beslut kräver att schemat ändras. Det är avsikten: ingenting får börja flöda över gränsen utan att kontraktet vet om det.
- **Version:** `x-api-version` i varje schemafil följer `smartbox/contracts.API_VERSION` (SemVer). Ny valfri nyckel = MINOR, ändrad eller borttagen nyckel = MAJOR.
- **Per bil** används nyckelmönster (`<bil>_limit_a`, `<bil>_panic`, `<bil>_set_phases`, `<bil>_kw`), så antalet bilar är inte hårdkodat.
- **Omvandling:** `smartbox/contracts.py` gör beslut och planer JSON-säkra (numpy-tal, NaN -> null, datum -> ISO-text) och filtrerar inget.

## Paritetsverktyget

`smartbox/parity.py` kör två implementationer av samma beslut på samma följd av indata och visar exakt var de skiljer sig. Före varje flytt körs
den gamla (i processen) och den nya sida vid sida, och bytet görs först när skillnaderna är noll:

    report = parity.compare(scenarios, make_old, make_new, normalize=contracts.decision_to_wire)
    assert report.ok, report.summary()

Scenarierna kan vara `tests/gpm_golden_gen.scenarios()`. Se `tests/test_contracts.py` för ett körbart exempel.
