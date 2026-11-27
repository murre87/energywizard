# Kontrakt mellan EnergyWizards delar

Det som passerar gränsen mellan Core och planeringen (och senare drivrutinerna) är en ren JSON-struktur med ett versionerat schema. Det är
det som gör att en del kan flyttas till en egen process eller ett eget repo utan att något tappas tyst.

| Schema | Riktning | I dag skapas det av |
| --- | --- | --- |
| `planner-decision.schema.json` | planering -> Core | `gpm.GlobalPriorityManager.evaluate` |
| `ev-plan.schema.json` | planering -> Core | `decisions.calculate_ev_charge_plan` |
| `battery-plan.schema.json` | planering -> Core | `battery_plan.optimize` |
| `driver-state.schema.json` | drivrutin -> Core | `read_state` (solen: `read_production`; spa: även effekt och aktiviteter) |
| `driver-command.schema.json` | Core -> drivrutin | metoderna på drivrutinens basklass (`apply_intent`, `set_*`, `turn_*`, `pause`, `resume`) |

## Regler

- **Facit är de riktiga anropen.** `tests/test_contracts.py` kör 2 600 beslut (gpm:s golden-scenarier), en riktig laddplan, riktiga batteriplaner från `optimize` och drivrutinernas egna `read_state`/`read_production` mot schemat. Kommandoargumenten följer metodsignaturen på basklassen.
- **Strängt:** `additionalProperties: false`. En ny nyckel i ett beslut kräver att schemat ändras. Det är avsikten: ingenting får börja flöda över gränsen utan att kontraktet vet om det.
- **Version:** `x-api-version` i varje schemafil följer `smartbox/contracts.API_VERSION` (SemVer). Ny valfri nyckel = MINOR, ändrad eller borttagen nyckel = MAJOR.
- **Per bil** används nyckelmönster (`<bil>_limit_a`, `<bil>_panic`, `<bil>_set_phases`, `<bil>_kw`), så antalet bilar är inte hårdkodat.
- **Omvandling:** `smartbox/contracts.py` gör beslut, planer, lägen och kommandon JSON-säkra (numpy-tal, NaN -> null, datum -> ISO-text) och filtrerar inget.
- **Batteriplanen** är det `optimize` lämnar. Det `plan_from_db` lägger på efteråt (`plan_id`, `action_now`, beställd effekt, indatakvalitet) är delat tillstånd och hör till steg 3.
- **Aktivitetsnamn och modul-id** kommer från installationen. Nycklarna är därför öppna, men värdenas form är låst.

## Paritetsverktyget

`smartbox/parity.py` kör två implementationer av samma beslut på samma följd av indata och visar exakt var de skiljer sig. Före varje flytt körs
den gamla (i processen) och den nya sida vid sida, och bytet görs först när skillnaderna är noll:

    report = parity.compare(scenarios, make_old, make_new, normalize=contracts.decision_to_wire)
    assert report.ok, report.summary()

Scenarierna kan vara `tests/gpm_golden_gen.scenarios()`. Se `tests/test_contracts.py` för ett körbart exempel.
