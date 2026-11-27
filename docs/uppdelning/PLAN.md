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
| 5b | Märkesspecifik kod ut ur `homeassistant.py` (Easee, SolarEdge, Gecko, bilens klimat, spabad) in i drivrutinerna | klart: `drivers/ha_easee.py`, `ha_solaredge.py`, `ha_gecko.py`, `ha_car.py` |
| 5c | Drivrutinerna flyttas till `energywizard-drivers` (med `host.py`, falsk värd, kontraktstester och CI); Core hämtar dem med fast version | klart: repot har `drivers/`, tester mot falsk värd och CI (tagg v0.1.0); Core har `release-manifest.json`, `scripts/sync_drivers.py` och `tests/test_release_manifest.py` |
| 5d | Resten av beroendena bakom värden: det som är drivrutinskod flyttar (`pump`, `spa_entities`, `lua_host`), det som är Core:s tjänster blir kvar som värdens permanenta yta | klart: drivrutinerna v0.2.0 |
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

## Märkeskoden ut ur värden (steg 5b)

Märkesspecifik kod låg i `homeassistant.py`. Den bor nu hos drivrutinerna, och värden har bara den generella delen kvar:

- `drivers/ha_easee.py` (läsa laddbox, dynamisk gräns, fasläge, på/av), `ha_solaredge.py` (läsa, exportgräns, standardnamnen), `ha_gecko.py` (läsa, effekt, aktiviteter, måltemperatur, Economy Mode, smartplugg), `ha_car.py` (bilklimat, uppdatera entitet).
- Värden fick två generella primitiver: `post_service("domän/tjänst", payload, timeout)` (går genom skuggläget som alla skrivningar, kastar vid fel) och `report_failure(text, fel)` (⚠️ för drift, ❌ för programfel). Allt märkesspecifikt (tjänstenamn, fasströmsattribut, fasläget som inte går att läsa tillbaka) är drivrutinens.
- `homeassistant.py` har tunna vidarekopplingar med de gamla namnen (`set_ev_dynamic_limit`, `set_easee_phases`, `turn_on_charger`, `turn_off_charger`, `_read_easee_charger`, `read_solaredge`, `get/set_solaredge_limit`, `read_gecko`, `set_gecko_*`, `toggle_spa_plug`, `read_spa_*`, `set_car_climate`, `refresh_entity`), så `main.py`, appen, webben och äldre tester fungerar oförändrat.
- `set_climate_temperature` blev kvar i värden: det är en generell `climate.set_temperature` som flera drivrutiner delar (värmepump, spa), inte märkeskod. Det avviker från den ursprungliga listan.
- Värdens yta för `homeassistant` krympte från 32 till 17 namn (`_BASE`, `_HEADERS` och `_VERIFY` behövs inte längre), vilket är det drivrutinsrepot måste erbjuda i steg 5c.
- Bevis: `tests/test_ha_brands.py` (märkesmodulerna mot en falsk värd utan motorns `homeassistant`, exakt samma HA-anrop och tidsgränser som förut, vidarekopplingarna, och att ytan inte längre har märkesnamn).

## Det sista bakom värden (steg 5d)

Av de tretton modulerna värden erbjöd efter 5a visade sig tre vara ren drivrutinskod, och de flyttade med till `energywizard-drivers` (v0.2.0):

- `pump.py` (Thermia/Husdata via Modbus) är nu `drivers/thermia_pump.py`, `spa_entities.py` (Gecko-badets entiteter) är `drivers/spa_entities.py` och `lua_host.py` (värd för FTW:s Lua-drivrutiner) är `drivers/lua_host.py`. Skuggläget och `HA_IP` når de via värden.
- I Core finns tre vidarekopplingar med de gamla namnen (`smartbox/pump.py`, `lua_host.py`, `spa_entities.py`). De byter ut sig själva mot drivrutinsmodulen (`sys.modules`), så `import pump` ger samma modulobjekt och motorn, webben och testerna som ändrar `pump.NAMN` fungerar oförändrat.
- Det som blir kvar i värden är **Core:s egna tjänster**, inte drivrutinskod: `homeassistant` (generella delen), `shadow`, `ew_settings`, `nordpool.price_timezone`, `hot_water_observation.temperature`, `hot_water_runtime.Journal`, `hot_water_reservations.boost_fields`, `support_bundle`, `telemetry.report_error` och `notifier.send_emil`. Det är den permanenta ytan en drivrutin får räkna med, och den är versionerad med kontrakten. Värdens moduler är 10 (var 13).
- Första riktiga släppet genom flödet: ändra i drivrutinsrepot, tagga v0.2.0, kör `--bump v0.2.0` i Core.

## Så håller vi ihop releaserna när delarna ligger i olika repon

Frågan (FlebbsRulez, Discord 2026-11-27): en fix i Core som delen Planner beror på måste levereras innan fix B i Planner kan påbörjas, annars blir det krockar.

1. **Kontraktet först, utöka och byt sedan ta bort.** En ändring som rör två delar görs i tre PR:er som inte låser varandra: (a) Core lägger till ett *valfritt* fält i kontraktet (MINOR, bakåtkompatibelt), (b) varje del börjar använda det, oberoende av varandra, (c) när alla använder det tas det gamla bort. Bara brytande ändringar (MAJOR) kräver att delarna släpps tillsammans.
2. **Core äger releasen.** En fil med fastlåsta versioner (release-manifest) i Core pekar ut exakta versioner av drivrutiner, planering och webb, och Core bygger dem in i en enda image. Användaren uppdaterar aldrig delarna var för sig. Fix B utgår från den version av A som manifestet pekar på, inte från A:s gren. En ändring i en del räknas som levererad först när Core-PR:en som höjer versionen är mergad och integrationstesterna är gröna.
3. **Krockarna begränsas av filplaceringen.** Delarna delar inga filer, bara kontraktet (`contracts/`), som Core äger.
4. **Beroenden mellan PR:er syns.** PR-mallen får en rad "Beror på: repo#nummer", och en CI-kontroll vägrar merge tills den PR:en är mergad.
5. **Kompatibilitet kontrolleras.** Varje del jämför kontraktets huvudversion vid start och vägrar starta vid fel (planeringstjänstens `/health` ger redan `api_version`). Varje delrepos CI kör kontraktstester mot Cores senaste och föregående kontrakt.
6. **Ändringslogg utan krockar.** Under 2026-11-27 krockade alla tio öppna PR:er på `ha-addon/smartbox/CHANGELOG.md` (varje PR lägger en versionspost överst) och tog flera timmar att reda ut. Varje PR bör i stället lägga en egen liten fil (`changelog.d/`) och versionen sätts vid släpp. Det rör släppkedjan (tilläggsbotten läser översta rubriken) och görs därför som ett eget, försiktigt steg.
7. **Grind innan fler delar delas ut.** Drivrutinerna delas först. Efter det mäts hur ofta en ändring rör flera repon. Är det ofta är en monorepo med kataloger, kodägare och en privat del som undermodul ett bättre svar än fler repon, och då slås delarna ihop igen (kontrakten och värdmodulen behövs ändå).

Byggt i steg 5c: **release-manifestet** (`release-manifest.json`: repo, tagg, commit och innehållsstämpel för drivrutinerna) och kontrollen av det, **versionskontrollen vid start** och **`Beror på`-kontrollen**. **Inte byggt än:** ändringsloggsfilerna.

- **Versionskontroll vid start:** drivrutinerna deklarerar vilken huvudversion av kontraktet de är skrivna mot (`REQUIRES_CONTRACT_MAJOR` i `drivers/host.py`, sedan v0.2.1). `main.py` anropar `check_compat(contracts.API_VERSION)` före allt annat och startar inte vid fel huvudversion. Eftersom drivrutinerna ligger fastlåsta i samma image kan en avvikelse bara uppstå vid ett utvecklingsfel, och `tests/test_drivers_compat.py` fångar det i CI innan det når någon installation.
- **`Beror på`-kontrollen:** PR-mallen (`.github/pull_request_template.md`) har raden `Beror på: ingen`. Skriv `Beror på: murre87/energywizard-drivers#12` (eller `#123` i samma repo), så är kontrollen `beror-pa` (`scripts/check_depends_on.py`) röd tills den PR:en är mergad. För att den ska *hindra* merge måste `beror-pa` vara en obligatorisk kontroll i grenskyddet för `main` (en inställning i GitHub, ägaren gör den). Kontrollen körs om när PR-beskrivningen eller koden ändras, men inte av sig själv när den andra PR:en mergas: tryck på "Re-run" eller redigera beskrivningen.

## Drivrutinerna i eget repo (steg 5c)

- **Repot** `murre87/energywizard-drivers` (publikt, AGPL-3.0) har `drivers/` (inklusive `host.py`), `tests/test_host_seam.py` (ingen drivrutin når motorn förbi värden, och ytan stämmer med användningen, utan motorn), `tests/test_brands_fake_host.py` (märkesmodulerna mot en falsk värd) och CI. Första taggen är `v0.1.0`.
- **Core vendrar** den fastlåsta versionen: `smartbox/drivers/` är byte för byte den taggade versionen (Dockerfilerna är oförändrade, bygget behöver ingen nätverkshämtning). `scripts/sync_drivers.py --check` jämför innehållsstämpeln med manifestet, och `tests/test_release_manifest.py` kör det i CI. En lokal ändring av en drivrutin i Core gör alltså CI rött.
- **Så ändras en drivrutin:** ändra i `energywizard-drivers`, tagga, kör `python scripts/sync_drivers.py --bump <tagg>` i Core och skicka en PR. Core:s hela testsvit körs mot den nya versionen. Ändringen räknas som levererad när den PR:en är mergad.
- **Konsekvens att veta:** pågående PR:er som rör `smartbox/drivers/` (till exempel nya drivrutiner) måste flyttas till drivrutinsrepot innan de kan mergas i Core.
