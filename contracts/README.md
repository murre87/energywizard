# Kontrakt mellan EnergyWizards delar

Det som passerar gränsen mellan Core och planeringen (och senare drivrutinerna) är en ren JSON-struktur med ett versionerat schema. Det är
det som gör att en del kan flyttas till en egen process eller ett eget repo utan att något tappas tyst.

| Schema | Riktning | I dag skapas det av |
| --- | --- | --- |
| `planner-decision.schema.json` | planering -> Core | `gpm.GlobalPriorityManager.evaluate` |
| `ev-plan.schema.json` | planering -> Core | `decisions.calculate_ev_charge_plan` |
| `planner-input.schema.json` | Core -> planering | `gpm_state` i `main.py` (det delade tillståndet) |
| `battery-decision.schema.json` | planering -> Core | `battery_control.decide` |
| `battery-plan.schema.json` | planering -> Core | `battery_plan.plan_from_db` |
| `driver-state.schema.json` | drivrutiner -> Core | `read_state`/`read_sensors`/`read_production` (`#/$defs/<typ>`) |
| `driver-command.schema.json` | Core -> drivrutiner | de skrivande metoderna på drivrutinsgränssnitten |

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

## Kontraktsvakten

`tests/contract_guard.py` kontrollerar varje drivrutinssvar, varje batteriplan och varje batteribeslut under HELA testsviten mot schemat. De tusentals
befintliga testerna är alltså mätkorpus: lämnar en drivrutin en ny nyckel med fel typ, eller ändras batteribeslutets form, blir just det testet rött med
exakt vad som avviker. Ett test som med flit lämnar ogiltiga data märks `@pytest.mark.no_contract_guard`. Mock-objekt hoppas över.

Drivrutinerna har några få sluddriga typer (heltal som bool, statuskod som tal). `contracts.normalize_driver_state` rättar bara de uppräknade fälten
(`BOOL_FIELDS`, `STR_FIELDS`) och lämnar allt annat orört, så en ny avvikelse syns i stället för att döljas.

## Så här ändrar du ett gränssnitt

- **Ny publik metod på ett drivrutinsgränssnitt:** `tests/test_contracts_drivers.py` kräver att den klassas som kommando (`contracts.COMMANDS`, plus schemat) eller icke-kommando (`NON_COMMANDS`).
- **Ny regel i batteribeslutet:** läggs till i `battery-decision.schema.json` (testet jämför mot koden).
- **Ny nyckel i ett beslut eller en plan:** schemat ändras och `x-api-version` höjs (ny valfri nyckel = MINOR, ändrad eller borttagen = MAJOR).

## Indatakontraktet (det delade tillståndet)

`planner-input.schema.json` beskriver allt Core lämnar till planeringen. `x-evidence` säger hur säker typen är: `golden` (uppmätt i de 2 600 scenarierna),
`main-code` (läst ur `main.py:s` uttryck) eller `unverified`. Alla nycklar är valfria, och `null` betyder att en givare saknas. `tests/test_contracts_input.py` jämför
nyckeluppsättningen mot koden åt båda håll (vad `gpm.py` läser, vad `main.py` skickar), så en ny, borttagen eller omdöpt nyckel ändrar kontraktet eller testet blir rött.
Ett test som med flit ger planeringen minimal eller konstig indata märks `@pytest.mark.no_planner_input_guard`.
