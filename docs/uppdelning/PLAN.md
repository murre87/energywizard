# Uppdelning av EnergyWizard: plan och logg

Underlag: *Arkitektur- och Migreringsplan för EnergyWizard* (Emil, 2026-11-27). Beslut för genomförandet:

- **Ingen Rust.** Uppdelningen görs i Python. Rust kan komma senare, och då för en liten, väl avgränsad del (säkerhetsskydden), inte för optimeringen.
- **Delarna:** Core (motor, API, säkerhetsspärrar, databas), drivrutiner, planering och ML, webb. Nativa appar är ett framtida spår.
- **Privata repon är tillåtna.** Åtkomst: `lazgeo` och Cursor-boten får tillgång till det privata. Övriga som skrivit kod i delar som blir privata får skriva avtal med Emil innan koden flyttas.
- **Synligheten avgörs sist.** Det tekniska arbetet är detsamma oavsett om en del är publik eller privat, så varje steg görs med allt publikt tills avtalen finns.
- **Inget får gå förlorat.** Varje del som flyttas jämförs först sida vid sida med den gamla (`smartbox/parity.py`) och byts bara när skillnaderna är noll. Planeringen får aldrig stoppa styrningen: Core fortsätter med senaste giltiga plan eller säkra standardvärden om planeringen inte svarar, och skyddsspärrarna (säkring, kompressor) ligger kvar i Core.

## Steg

| # | Steg | Status |
| --- | --- | --- |
| 1 | Kontrakt för planerarens överlämning (beslut och laddplan) + paritetsverktyg, utan att flytta kod | klart (`contracts/`, `smartbox/contracts.py`, `smartbox/parity.py`) |
| 2 | Kontrakt för batteriplanen, batteribeslutet och drivrutinernas state och kommandon, plus en kontraktsvakt över hela testsviten | klart (`contracts/`, `tests/contract_guard.py`) |
| 3 | Det delade tillståndet (det Core lämnar till planeringen) uttryckligt i kontraktet: `planner-input.schema.json`, jämfört mot koden åt båda håll, plus indatavakt över hela testsviten | klart |
| 4a | Förarbete: stäng täckningsglappet (utökat facit `tests/gpm_ext_gen.py`) och städa de sex oanvända indatanycklarna | klart |
| 4b | Planeringen som egen process i samma image (Python), i **skuggläge**: den gamla vägen styr, den nya körs bredvid och jämförs (`EW_PLANNER_MODE=shadow`, standard `local`) | klart: `planner_service.py`, `planner_bridge.py`, `contracts.planner_input_from_wire` |
| 4c | Köra skuggläget mot din egen installation i några dygn och se paritet på riktig data (inga skillnader efter uppvärmning) | |
| 4d | Läget `remote`: planerarens process styr, den gamla vägen är fallback (senaste giltiga plan, sedan den gamla vägen); notiser flyttas dit | |
| 5a | Sömmen: drivrutinerna når Core bara genom en modul (`drivers/host.py`) som Core binder vid start; kontraktstester mot en falsk värd | |
| 5b | Märkesspecifik kod ut ur `homeassistant.py` (Easee, SolarEdge, Gecko, bilens klimat, spabad) in i drivrutinerna | |
| 5c | Drivrutinerna flyttas till `energywizard-drivers` (med `host.py`, falsk värd, kontraktstester och CI); Core hämtar dem med fast version | |
| 5d | Resten av beroendena (`pump`, `hot_water_*`, `spa_entities`, `telemetry`, `notifier`, `support_bundle`) bakom värden | |
| 6 | API i Core (REST/WebSocket); appen och webben flyttas över ett område i taget, med den gamla vägen kvar tills den nya är verifierad | |
| 7 | Release-kanaler (stable/dev), synlig version och versionskoll | |
| 8 | Flytta det som får vara privat (efter avtal) | |

## Risker att bevaka

- **Delat tillstånd.** `main.py` (3 250 rader) delar variabler, överstyrningar och cacher mellan delarna. Allt som planeringen läser eller skriver måste in i kontraktet innan koden flyttas (steg 3).
- **Nya felvägar** när delar pratar över HTTP: tidsgränser, planeringen nere, gammal plan. Core ska alltid ha ett säkert beteende.
- **HA-tillägget** kör normalt en container per tillägg: delarna körs som processer i samma image där.
- **Upphovsrätt och licens.** Koden är AGPL-3. Bidragsgivare (bland andra `lazgeo`, `flebbhue`, Michal Koláček, Jonatan Åkerlind) behåller upphovsrätten till det de skrivit. Avtal ska finnas innan deras kod ligger i ett privat repo eller levereras som körbar fil utan källkod. FTW-härledda AGPL-drivrutiner (`smartbox/ftw_drivers/`) får inte hamna i ett privat repo.

## Fynd från steg 3

- **`heat_glide_hours`** läses av `gpm.py` (standard 3 timmar, kommentaren kallar den en inställning) men `main.py` skickar den aldrig, så den kan inte ändras. Beteendet är oförändrat. Kopplas när den får en inställning.
- **Sex nycklar** skickades av `main.py` men lästes aldrig av `gpm.py` (`base_load_profile`, `ev_max_charge_a`, `ev_min_charge_a`, `grid_import_w`, `house_consumption_w`, `power_limit_kw`). Borttagna i steg 4a: `gpm_state` går bara till `evaluate`, och ingen annan modul läste dem ur den.
- **Testtäckning (åtgärdad i 4a):** 34 av de 75 nycklar `gpm` läser förekom inte i de 2 600 facit-scenarierna (värmeåterkoppling, bortaläge, varmvattnets ML, spaextra). En ändring av bortalägets frostskydd (15 till 14 °C) passerade `test_gpm_golden.py` utan att synas. Nu täcker `tests/gpm_ext_gen.py` (2 080 beslut) allt utom `heat_glide_hours`, och samma ändring gör `tests/test_gpm_golden_ext.py` rött.
- **`outdoor_avg_5d`** hade tidigare en buggkommentar i `main.py` ("saknades -> is_summer var alltid False"): just den sortens glapp fångas nu av kontraktstestet.

## Planeringen som egen process (steg 4b)

- **Tjänsten** (`smartbox/planner_service.py`): en liten HTTP-tjänst på 127.0.0.1 med bara stdlib (inga nya beroenden). `POST /decide` tar planner-input och ger planner-decision enligt kontrakten, `POST /reset` ger en ny motor, `GET /health`. Motorn är tillståndsfull, så alla anrop går genom samma instans under lås. Starta: `python planner_service.py --port 8610`.
- **Bryggan** (`smartbox/planner_bridge.py`), vald med `EW_PLANNER_MODE`:
  - `local` (standard): ingen skillnad mot förut.
  - `shadow`: den gamla vägen styr fortfarande och är det som returneras. Samma indata skickas i bakgrunden till tjänsten (som bryggan startar som underprocess och startar om vid behov, högst en gång per 30 s och fem gånger i timmen), och besluten jämförs med paritetsverktyget. Skillnader loggas (högst en gång per tio minuter per skillnad), och en sammanfattning skrivs var 15:e minut. De första 8 svaren efter varje start räknas som uppvärmning, eftersom den nya motorn börjar utan historik.
- **Bryggan stör aldrig huvudloopen:** den väntar inte på tjänsten (ett pågående anrop gör att nästa hoppas över, ingen kö), fel fångas och räknas, och ett fel i bryggan själv når inte `main.py`.
- **Tyst tjänst:** i skuggläge ersätts `gpm.notifier` så att inga notiser skickas dubbelt. `--loud` (steg 4d) låter tjänsten skicka.
- **Minne:** tjänsten är en egen Python-process som laddar `gpm` och dess beroenden (bland annat scikit-learn), så skuggläget kostar ungefär lika mycket minne som motorn en gång till. Håll det av på små enheter tills steg 4c har visat att det behövs.
- **Bevis:** `tests/test_planner_wire.py` (alla 4 680 facit-steg ger samma beslut efter en tur genom JSON) och `tests/test_planner_service.py` (samma beslut över riktig HTTP och med en riktig underprocess, bryggans beteende med falska delar).

## Kopplingen mellan drivrutinerna och resten (uppmätt före steg 5)

30 drivrutinsfiler (plus 98 FTW-Lua-drivrutiner som redan är fristående) importerar 13 moduler ur resten av motorn. Bara fem moduler importerar tillbaka
(`main`, `house_config`, `battery_plan`, `battery_shadow`, `nibe_hot_water_audit`), så ingångarna är få. Utgående beroenden (modul: antal drivrutiner):

- `homeassistant` (14): ungefär 30 funktioner. Läsning av state (`_get_numeric_state`, `_get_raw_state`, `get_attribute`, `get_power_w`) och skrivning
  (`set_number`, `set_switch`, `set_select`, `call_service`, `press_button`) är generella. Resten är **märkesspecifik kod som bor i `homeassistant.py`**:
  `set_ev_dynamic_limit`, `set_easee_phases`, `turn_on_charger`, `turn_off_charger`, `_read_easee_charger`, `read_solaredge`, `get/set_solaredge_limit`,
  `read_gecko`, `set_gecko_target`, `set_gecko_economy`, `toggle_spa_plug`, `read_spa_power`, `read_spa_activities`, `set_car_climate`,
  `set_climate_temperature`. De hör hemma i drivrutinerna (steg 5b), och bara den generella delen blir kvar i värden.
- `shadow` (7): `active()` och `record()` (skuggläget).
- `hot_water_observation` (4): `temperature`. `ew_settings` (2): `get`, `PATH`.
- Enstaka: `nordpool.price_timezone`, `hot_water_runtime.Journal`, `support_bundle.sanitize/note_error_line`, `lua_host.LuaDriver`, `telemetry.report_error`,
  `notifier.send_emil`, `hot_water_reservations.boost_fields`, `pump.*` (8 funktioner, Thermia), `spa_entities.complete_gecko`.

Sömmen (5a) är alltså en liten värdmodul med ungefär 15 generella funktioner; resten är kod som flyttar med drivrutinerna.
