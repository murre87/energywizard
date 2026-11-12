# Roadmap

Inte löften om datum - bara vad som är nästa rimliga steg och varför, så det är
tydligt vad som redan är beslutat och vad som väntar på mer underlag.

## Beslut

- **Licens: AGPL-3.0 - beslutat 2026-11-03.** LICENSE-filen finns i repots rot. Samma licens som
  [FTW](https://github.com/srcfl/ftw), så kod därifrån får nu också återanvändas (med källhänvisning).

## Att göra (önskemål från Discord och Emil, 2026-11-04)

- **FTW-drivrutiner: verifierad styrning.** Läsning fungerar sedan 2026-11-05 (`driver: ftw`, alla 93 medföljer). Kvar:
  prova styrning (driver_command) på riktig hårdvara drivrutin för drivrutin och lägga in dem i `FTW_CONTROL_VERIFIED`
  – Sungrow, Sonnen, Victron och SMA först. Guiden namnger FTW-drivrutinen (deye, sigenergy, solinteg, pixii) när Home Assistant kan läsa märket men inte styra batteriet. Användaren fyller i IP själv, och styrning förblir av.
- **Tillägget använder färdigbyggda images** – klart 2026-11-06: CI-jobbet `tillagg` taggar imagen med tilläggets
  version och höjer `version` i config.yaml först när imagen är pushad (ny version = ny rubrik i CHANGELOG.md).
- **Testa Modbus-drivrutinerna mot srcfl/device-simulator i CI** (Solax, Ferroamp, Thermia, Pixii) - utan hårdvara.
  (Kollat 2026-11-07: simulatorn byggs från Go-källkod och har profiler för Sungrow, SolarEdge, Fronius, Huawei, SMA,
  Solis, Deye och Pixii, men inte för Solax, Ferroamp eller Thermia. Mest värde för FTW-drivrutinerna.)
- **Max laddström och faser känns av själv** – klart (`ev_limits.py`): lärs av laddboxens fasströmmar där
  installationen inte anger `phases`/`max_a`. Startguiden visar det inlärda vid bilens id (och övriga inlärda
  id:n), och den nedladdade konfigurationen får en kommentar. `phases` och `max_a` skrivs inte in, så de kan
  fortsätta läras.
- **Drivrutiner från evcc** ([evcc-io/evcc](https://github.com/evcc-io/evcc), MIT, får användas i AGPL med upphovsrättsraden
  kvar). evcc har YAML-mallar för 211 laddboxar, 251 mätare, växelriktare och batterier och 72 bilar, som pratar direkt
  med enheten via Modbus, HTTP eller MQTT. Mest värde ger det där Home Assistant bara kan läsa men inte styra:
  batterier och växelriktare som Victron, Sigenergy, Pixii, Huawei och GoodWe. Två vägar:
  (1) en liten tolk för evcc:s Modbus/HTTP-mallar i Python, som ger många mätare och batterier på en gång;
  (2) en körande evcc som laddbackend via dess API eller MQTT. Börja med (1) för batterierna som betatestarna har.
- **Pixii (PowerShaper / Home).** Läsning fungerar nu via `driver: ftw` + FTW:s `pixii`-drivrutin (SunSpec 802, tecknet
  hanteras av drivrutinen). Styrning: Pixiis egna register + heartbeat (FTW `pixii`, overifierad på hårdvara) – slås på
  när en testare med Pixii provat (`control_unverified: true` + skuggläge först).
## Klart 2026-11-05 (natten, Emils mandat)

- **Planvyn Skyline** på förstasidan i appen och på webben, med planklockan som val (urtavlan låg för nära FTW:s
  design och är bara ett val nu). Egen färg när batteriet laddar ur och säljer; batteriraden "Laddar ur till 09:45".
- **Ensidigt exportskydd**: med export avstängd laddar batteriet aldrig ur mer än huset köper (−50 W marginal).
- **Tomt fält sparas aldrig som 0**: genomgånget – tomt ger standardvärde eller avvisas, gränser stoppar farliga nollor.
- **Rum, lampor, namn och peppfraser** ur installationen/inställningarna, inget av Emils i koden.
- **Gästbil** (#131): kWh + ev. klar-tid på valfri bils laddbox, billigaste kvartarna, under säkringen. Easees fasväljare
  fanns redan (faser `auto`).
- **Effektavgift efter högsta timmar** (#141): Norges effektledd och svenska "snitt av N högsta timmar" med trappsteg.
- **FTW-drivrutiner i motorn**: `driver: ftw` för batteri och solceller, alla 93 medföljer, läsande; styrning per
  verifierad drivrutin. Lua-bryggan verifierad mot en riktig Shelly 3EM.
- **Sex nya batteriförinställningar**: GoodWe, SolarEdge, Sungrow, Huawei LUNA, Tesla Powerwall, Enphase (ej verifierade
  på hårdvara). Kartläggning av de 20 vanligaste i docs/batterier-och-vaxelriktare.md.
- **Besparingen** räknas mot ett vanligt hushåll inklusive moms. **Installationens logg** (Logg-sidan). **Varning när
  batteriet inte följer** och **alla notiser går att stänga av**.

## Övervägs, väntar på fler verkliga hus att verifiera mot

Från genomgången av [FTW](https://github.com/srcfl/ftw) 2026-11-03 (AGPL-3.0-only, får återanvändas med källhänvisning;
optimeraren Energyplan är stängd och används inte):

- **Emaldo (husbatteri).** Önskat 2026-11-04. Det finns en HA-integration,
  [wertigpar/ha-emaldo](https://github.com/wertigpar/ha-emaldo) (MIT, HACS). Den ger laddnivå, effekt, nät, last, sol och
  elbil, plus override-tjänster för att styra batteriet. Batteriets egen schemaläggare
  [wertigpar/ha-battery-optimizer](https://github.com/wertigpar/ha-battery-optimizer) (MIT) gör en 15-minutersplan efter
  spotpris och solprognos och skickar den till Emaldo. Plan: en förinställning som läser Emaldo-integrationens entiteter.
  Styrningen sker antingen via Emaldos override-tjänster eller genom samarbete med Battery Optimizer
  (läget `samarbete`: läs, styr inte), på samma sätt som med Predbat. Behöver en testare med Emaldo.
- **Sonnen (sonnenBatterie).** Önskat 2026-11-04. Lokalt API på batteriet; det finns HA-integrationer för läsning och
  driftläge (egenförbrukning, manuell laddning/urladdning). Plan: förinställning för läsning + lägena
  auto/ladda/ladda ur. Behöver en testare med Sonnen.
- **Solproduktion från flera växelriktare.** Klart 2026-11-07 för den generiska soldrivrutinen: `sum_inverters: true`
  summerar listan i `pv_power_w`/`today_kwh` (utan den är listan reserv). Guiden föreslår det själv från 2026-11-12:
  en solgivare per växelriktare, och strängar/MPPT bara när den växelriktaren saknar en egen solgivare.
- **Flera batterier och växelriktare samtidigt.** Idag ett batteri och en solcellsdrivrutin. Fördela effekten efter
  laddnivå och kapacitet, med gemensam säkringsgräns (FTW: multi-battery allocation). Efterfrågat av #78 (tre GoodWe +
  Ferroamp) och #86 (två Solax).
- **Inbyggd OCPP-server.** Laddboxar (Charge Amps, Zaptec, Alfen ...) kopplas direkt till EnergyWizard utan OCPP-integration
  i HA (FTW: OCPP 1.6J + 2.0.1). Stort jobb, men sänker tröskeln.
- **Mjuka effektändringar (slew rate).** Batteriets effekt ändras gradvis i stället för i hopp; säkringsskyddet får
  fortfarande agera direkt.
- **Verifieringsnivå per drivrutin.** "Körs i N hem" bredvid varje märke på webben och i README, automatiskt ur
  telemetrin (FTW märker sina drivrutiner verifierad/inte verifierad på hårdvara). FTW:s katalog med 92 drivrutiner
  ([drivers.json](https://srcfl.github.io/device-drivers/drivers.json)) är en bra uppslagsbok för vilka märken som går
  att styra och hur - som referens, vi fortsätter gå via HA:s integrationer.

- **Värmepumpar: styrning via Matter-lagret (pausat 2026-11-03, Emils beslut).** Gränssnittet finns
  redan (`drivers/heatpump.py`: läge, effekt, COP, fel, kurva ±n med tak ±5, paus med tidsgräns,
  nollställning vid start) och HeishaMon (Panasonic) använder det. Motorn styr dock fortfarande
  pumparna som förut (rumsbörvärde, Thermia-lägen); att låta prioritetsmotorn använda kurva/paus
  för andra märken väntar. Liksom att flytta Thermia/NIBE till de nya krokarna.
- **Elpris och avgifter utanför Sverige (önskat av betatestare 2026-11-03).** Standardkällan är SE3
  (elprisetjustnu.se); andra Nord Pool-områden går via HA:s Nordpool-integration, men nätavgift, skatt och
  moms är svenska. Önskat: Octopus Agile (Storbritannien, #86), Amber (Australien, #83), Nederländerna (#88),
  Norge (#90). Kräver priskälla per land och avgifter som går att ställa in.
- **Pool och ackumulatortank efter elpris.** Poolvärme (#76) och elpatron i ackumulatortank (#47, Mattias på
  Facebook) - samma motor som spabadet, men med tankens temperatur som "laddnivå".
- **Återbetalning av energiskatt för lagrad el i batteri.** Den som har ett batteri kan få tillbaka
  energiskatten för el som köpts, lagrats och sedan matats ut på nätet (Skatteverket). Kräver att
  laddning från nät och urladdning till nät räknas kvart för kvart och sammanställs per år, som FTW
  visar i historiken. Bygg när ett riktigt batteri kör, så att siffrorna går att stämma av.

- **Husbatteri: steg 1-2 byggda (läsa, visa, regler i motorn) + samarbetsläge -
  overifierat mot riktigt batteri.** `smartbox/battery_control.py` fattar besluten med
  hela husets läge som indata: gammal data -> växelriktaren tar över; säkring/effekttak
  -> ladda ur; minuspris -> ladda; elbilen laddar från nätet -> håll (töm inte batteriet i
  bilen); elbilen solladdar över prioritetsnivån -> vila; reservnivå -> håll; billig timme
  med dyrare kvar -> håll; annars självförbrukning. Tre lägen: `samarbete` (standard -
  läser bara, för BESS/Predbat), `styr`, `av`. Avsikterna mappas till batteriets egna
  lägen i configen (`modes:`). Skyddsnät från FTW: auto vid start och SIGTERM, lägesbyten
  högst var 5:e minut. Inspiration: evcc (batteri+elbil), FTW (säkerhet), Predbat
  (märkesmappning). **Steg 3, dygnsplan (byggd, overifierad mot riktigt batteri):**
  `smartbox/battery_plan.py` - dynamisk programmering kvart för kvart över resten av
  dygnet och morgondagen med fullt köp-/säljpris, husets lastprofil, solprognos,
  elbilens plan, verkningsgrad, reservnivå och en kostnad per lägesbyte (sammanhängande
  plan, färre skrivningar). Räknas om var 15:e minut i läget styr, sparas i
  `battery_plan_slots` och syns i planvyn, tidslinjen och "Just nu" med beräknad
  besparing mot ren självförbrukning. Säkerhetsreglerna går alltid före.
  **Planen lär sig** (`smartbox/battery_learning.py`): verklig verkningsgrad och
  användbar kapacitet (kWh in/ut per procent), faktisk maxeffekt och solprognosens fel
  per timme - används bara med tillräckligt data och inom rimliga gränser. Uppmätt
  besparing per dag (nätkostnad utan batteri minus med). **Solax Modbus**
  (wills106) känns igen av entitetsväljaren med förifyllda lägen för Solax Gen4-6 och
  Growatt (inkl. "Time 1 Update"-knappen); drivrutinen klarar flera val per läge och
  separata ladd-/urladdningssensorer.

  **Predbat, inte [FTW](https://github.com/srcfl/ftw), är referensen för
  själva batteribeslutslogiken** den dagen det byggs: Predbat kör inuti Home
  Assistant (samma plattform vi redan kräver), har redan verifierat stöd för
  GivEnergy/Solis/Huawei/SolarEdge/Sofar/Tesla Powerwall m.fl., och är
  betydligt mer moget (365 stjärnor, 5 391 commits) än FTW (22 stjärnor,
  övergivna 2.x/3.x-linjer). FTW:s enda bidrag hit är ett specifikt, smalt
  mönster: dess opt-in-skrivväg för batteri/solöverskott har en dead-man
  switch (slutar skriva om den inte hör av sig), en tydlig återgång till
  standardläge, och en uppstarts-sweep som städar bort gamla/föräldralösa
  kommandon - värt att återanvända som skyddsnät oavsett vems beslutslogik
  `gpm.py` till slut bygger på.

  **Princip, gäller alla externa projekt vi tittar på, inte bara batteriet:**
  vi ska luta oss mot redan underhållen kod (Predbat, HA:s egna
  integrationer) så mycket som möjligt istället för att bygga och underhålla
  en egen optimerare - minimal egen kodyta, inte en konkurrerande
  implementation. Vi bygger INTE en egen batterioptimerare som konkurrerar
  med Predbats - målet är att komplettera den, inte ersätta den.

  **Koordinering med Predbat, redan utredd:**
  - ~~Steg 1, läs Predbats batterieffekt in i solöverskottsberäkningen~~ -
    **redan löst av arkitekturen, inget att bygga.** `gpm.py`:s
    `avg_net_w` (styr all solöverskott-logik: elbilsladdning, spabad,
    husvärme) kommer från Tibber Pulse och mäts VID HUVUDSÄKRINGEN
    (`homeassistant.read_tibber_data()`, P=U×I på alla tre faser) - alltså
    EFTER att batteriet redan tagit sin del. Om Predbat laddar batteriet
    från solöverskottet syns det automatiskt som mindre överskott i
    `avg_net_w`, utan att vi behöver läsa batteriets effekt separat. Ingen
    dubbelräkning existerar, eftersom vi aldrig räknar fram överskott från
    solproduktionen i sig - vi mäter den riktiga nettosiffran vid mätaren.
    Enda kvarvarande teoretiska risk: två oberoende system kan reagera på
    samma momentana överskott i samma ögonblick - en generell racing-fråga,
    dämpad redan idag av `gpm.py`:s rullande medelvärde (`avg_net_history`).
  - **Steg 2, samplanering - exportsensorn byggd, overifierad mot riktig Predbat.**
    `sensor.smartbox_planerad_last` (`smartbox/planned_load.py`, publiceras av
    `ha_publisher.py`) har elbilens laddplan i attributet `predbat`, i det format
    Predbats `load_forecast` läser: `{tidsstämpel med tidszon: stigande kWh}`.
    Formatet är kontrollerat genom att läsa Predbats källkod
    (`apps/predbat/fetch.py`: `fetch_extra_load_forecast` + `get_from_incrementing`),
    inte gissat. Varje 15-minutersslott får en punkt vid start och slut, så att
    Predbats utjämning inte smetar ut energi över luckorna. Bara elbilen ingår,
    eftersom värmepump och spabad inte har någon plan framåt. Konfiguration och
    dubbelräkningsrisken (`car_charging_hold`) står i
    [kunskapsbanksartikeln](https://murre87.github.io/energywizard/kunskapsbank/husbatteri.html).
    8 tester (`tests/test_planned_load.py`). Aldrig kört mot en riktig
    Predbat-installation: ingen betatestare med batteri + Predbat än.

- **OCPP-laddare via Home Assistants egen OCPP-integration - kopplad, overifierad mot
  riktig laddare.** Motorn skriver nu via laddardrivrutinerna (förut gick ALL strömstyrning
  direkt till Easees tjänster, så generiska/OCPP-laddare styrdes aldrig). Lärdomar från
  [SpotNav](https://github.com/henrikekblad/spotnav-home-assistant) (MIT, bekräftat på Charge
  Amps HALO): strömgränsen skrivs till sessionens gräns (`*_session_current_limit`), ALDRIG till
  laddboxens bestående `*_maximum_current`; under 6 A höjs till 6 A och 0 A stänger av laddningen;
  högst en skrivning per 10 s; OCPP-connector-status normaliseras (Available/Preparing/Charging/
  SuspendedEV...). Entitetsväljaren föreslår switch, connector-status, sessionsgräns och
  `current_import`. Easee oförändrat (samma anrop via sin drivrutin). Signalen
  `binary_sensor.smartbox_elbil_laddar_fran_natet` låter Predbat/EMHASS/en BESS låta bli att tömma
  batteriet i bilen.

- **Exportstyrning för fler växelriktare - byggd, overifierad mot riktig hårdvara.**
  Via redan underhållna HA-integrationer, ingen egen protokollkod (se
  [kunskapsbanken](https://murre87.github.io/energywizard/kunskapsbank/vaxelriktare.html)):
  Growatt (0xAHA/Growatt_ModbusTCP, gräns i % - fungerade redan med
  `generic_number`), Sungrow (mkaiser Modbus-paket, gräns i W + lägesbrytare -
  `generic_number` räknar nu om % till W), Huawei (wlcrs/huawei_solar:s tjänster,
  bekräftade mot integrationens `services.yaml`/`services.py` -
  `drivers/solar_huawei.py`) och Fronius (HA:s inbyggda `modbus.write_register`,
  WMaxLimPct/WMaxLim_Ena - `drivers/solar_modbus_register.py`; registeradresserna
  är omdiskuterade i communityn, därför konfigurerbara). Entitetsväljaren föreslår
  nu bara en %-gräns som %-gräns (tidigare kunde en W-gräns få värdet 0-100 och
  strypa exporten till ~100 W), en W-gräns som `export_limit_w`, och Huawei-
  drivrutinen med växelriktarens enhets-ID. 19 mockade tester (17 drivrutin, 2 entitetsväljare).

- **Fler värmepumpsmärken** (IVT, CTC, Mitsubishi, Viessmann m.fl.) -
  arkitekturen (`smartbox/drivers/heatpump.py`) är byggd för det, men varje
  märke kräver en egen, verifierad implementation - bidrag välkomna.

- **NIBE S-serie: lokal REST-drivrutin, ännu inte hårdvaruverifierad.**
  `drivers/heatpump_nibe_local.py` (`nibe_local`) använder HTTPS, Basic-auth
  och obligatorisk SHA-256-certifikatpinning före autentisering. Upptäckt sker
  via API:ets `deviceIndex`. För S1155/S1255 finns metadata-kontrollerade
  temperaturavläsningar och kompressorstatus; andra modeller kräver egna
  verifierade bindningar. Explicita, valfria skrivbindningar stöder rumsmål,
  varmvattenstart/stopp, värmestart och driftläge, med gränskontroller och
  separat återläsning. Skrivning är avstängd som standard; inga universella
  driftlägeskoder eller skrivregister antas. Tillfälliga boostar, AUX-blockering,
  paus och kurvjustering ingår inte. Tester använder enbart syntetiska svar;
  fysisk funktion och firmwarekompatibilitet återstår att verifiera.
  Se [konfiguration och begränsningar](docs/nibe-local-rest.md).

- **NIBE/Bosch/Atlantic/Daikin via myUplink - drivrutin byggd, aldrig körd mot
  ett riktigt konto.** `drivers/heatpump_myuplink.py` pratar med NIBE:s delade
  molnplattform myUplink, som enligt
  [FTW:s enhetskatalog](https://srcfl.github.io/device-drivers/drivers.json)
  även används av Bosch, Atlantic och Daikin - EN drivrutin täcker alltså
  flera märken. **Bekräftat mot myUplinks officiella OpenAPI-spec**
  (`https://api.myuplink.com/swagger/docs/public-v2/swagger.json`): bas-URL,
  `GET /v2/systems/me`, `GET`/`PATCH /v2/devices/{deviceId}/points`,
  token-URL, scopes READSYSTEM/WRITESYSTEM, och `ParameterData`-fälten
  (parameterId/parameterName/value/writable/min/max). **PATCH-kroppens form**
  (`{"<parameterId>": "<värde som sträng>"}`) är bekräftad via två oberoende
  community-rapporterade riktiga anrop (en Home Assistant- och en
  openHAB-issue), inte direkt citerad ur spec-filen - ett steg svagare källa
  än allt annat i drivrutinen, dokumenterat i modulens docstring.

  Genuint annan autentisering än resten av EnergyWizard: specens
  säkerhetsschema heter missvisande "Client Credentials", men en riktig,
  fungerande klient (home-assistant-myuplink) bekräftar att en INTERAKTIV
  webbläsarinloggning + samtycke krävs EN gång. `scripts/myuplink_authorize.py`
  gör det engångssteget och skriver ut en `refresh_token` att lägga i `.env` -
  headless därefter (ingen webbläsare behövs för normal drift). Som NIBE-lokal
  gissar drivrutinen inte på vilket parameterId som betyder vad för ett visst
  märke - användaren konfigurerar själv `heat_pump.entities` i
  `house_config.yaml` med parameterId:n hen hittar via `GET
  /v2/devices/{deviceId}/points`. 9 mockade tester, grönt - **aldrig körd mot
  ett riktigt myUplink-konto**, inget hus i projektet har ett.

- **Balboa-spabad: drivrutin byggd, väntar på verifiering mot riktig
  hårdvara.** `drivers/spa_balboa.py` finns nu - byggd mot HA:s officiella
  `balboa`-integrations DOKUMENTERADE entitetsformer (climate/select/switch/
  fan), inte en gissad protokolltolkning som den tidigare Gecko-genvägen var.
  Fortfarande aldrig körd mot ett riktigt Balboa-system (bara mockade
  tester) - har du ett Balboa-spabad? Hör av dig, det är precis den sortens
  verkliga installation som behövs för att bekräfta den.

- **Delad ML-modellträning på poolad data** från flera hus (bättre solprognoser,
  prismönster). **Telemetrilagret finns nu, är publikt nåbart och PÅ SOM
  STANDARD** (`smartbox/telemetry.py` - skickar bara hashad husidentifierare,
  aktiva drivrutinkategorier, feltyp och version, ingen sensorhistorik;
  obligatorisk sedan 2026-11-06, Emils beslut: går inte att stänga av). Beslutat 2026-11-01: tidigare
  strikt opt-in (av som standard), ändrat till på som standard för att faktiskt
  samla in data från fler installationer. På
  `https://energywizzard.profitalgos.com/telemetry` (standard i
  `.env.example`), med en reservväg via `ha-gateway`
  (`murrehtpc.axfors.se:8198/telemetry/`, overifierad utifrån - kräver
  portvidarebefordran i routern om den ska användas). Själva den poolade
  modellträningen är fortfarande inte byggd - det här är bara grunden som
  data kan börja samlas på.

- **EMHASS ([emhass.readthedocs.io](https://emhass.readthedocs.io/en/latest/),
  [GitHub](https://github.com/davidusb-geek/emhass)) som ett valfritt,
  framåtblickande planeringslager vid sidan av EnergyWizards egen, reaktiva
  motor.** Genuint annan ansats, inte en duplicerad bit: EMHASS löser ett
  riktigt LP-optimeringsproblem (pris-/solprognos → optimalt schema framåt),
  medan `gpm.py` fattar minut-för-minut-beslut utifrån nuläget. EMHASS saknar
  helt elbilsladdning, spabad och direkt Modbus-styrning (pratar bara med
  HA:s entiteter/tjänster) - skulle alltså komplettera, inte ersätta, det
  EnergyWizard redan gör. Inget konkret utkast än - en idé värd att utforska,
  inte ett beslutat nästa steg.
  
- **Frivillig telemetri och felrapportering (Opt-in crash/telemetry-tjänst)**. Liknande FTW:s molnlösning (`ftw-cloud` / drivrutinstelemetri). En lättviktig, självhostad central serverendpoint som tar emot anonyma felrapporter, stack traces och drivrutinsstatus från installationer som godkänner det. Syftet är att snabbt upptäcka krascher i skarpa hem utan att användare behöver manuellt posta loggar i issues. Lokalt läge förblir 100 % självständigt och fullt fungerande utan uppkoppling mot telemetriservern.

- **Box-signerad telemetri och felrapportering (FTW-modell)**. Frivillig molnuppkoppling mot egen server (`cloud.energywizard...`). Varje installation genererar ett unikt box-nyckelpar som signerar telemetri och felrapporter anonymt. Möjliggör att automatiskt upptäcka krascher, se vilka drivrutiner som fungerar i verkliga hem ("verifierad i N hem") och särskilja enstaka edge-cases från breda buggar utan att lagra personuppgifter.

## Redan klart

- **"Lägg till i Home Assistant"-knapp för Supervisor/HAOS-användare**
  (`ha-addon/smartbox/`, `repository.yaml`, samma `my.home-assistant.io`-
  genväg som [EMHASS](https://github.com/davidusb-geek/emhass)). Sedan 1.1.0
  paketeras även `webdashboard` (port 8503) och `ewapp` (port 8502) i samma
  container, inloggade med tilläggets `dashboard_password`, så engångs-notisen
  om tom konfiguration pekar nu på en adress som finns. Tilläggets inställningar
  läses nu också in från `/data/options.json` (tidigare lästes de aldrig, så
  telemetrireglaget hade ingen effekt). Postgres bundlas lokalt i
  tilläggscontainern (ett enkelt startskript, inte s6-overlay - dokumenterat
  avsteg i Dockerfile-kommentaren). **Verifierat:** startskriptet kört med
  bildens mapplayout (Postgres, motor, båda gränssnitten, inloggning, intern
  proxy webdashboard→ewapp, omstart av kraschat gränssnitt), och bilden byggs
  och röktestas i CI (`tester.yml`, jobbet `ha-tillagg`). **Overifierat:** har
  aldrig körts mot en riktig HAOS/Supervisor-installation - "Lägg till
  repository"-flödet, Supervisorns egen validering av `config.yaml`, och den
  riktiga `homeassistant_api`-proxyn är alla otestade här. Gränssnitten går via
  egna portar, inte HA:s ingress/sidomeny.

- **Termisk säkringsmodell för effektvakten - byggd, mockat verifierad, inte
  körd i ett riktigt hus än.** `smartbox/fuse_guard.py` följer
  [FTW:s `safety.md`](https://github.com/srcfl/ftw/blob/master/docs/safety.md):
  varje fas I² lågpassfiltreras med 60 s tidskonstant (Tibbers 10-sekundersprov),
  bilarna stryps när den filtrerade strömmen går över säkringen - eller direkt i
  10-sekundersloopen när en avläsning går över 1,2 × säkringen - och en laddande bil
  får bara öka när ökningen ryms, aldrig inom 20 s efter en strypning. En kort topp
  (vattenkokare, ugn) stryper alltså inte längre bilen. Ersätter den gamla formeln
  "säkring - husets minutsnitt" på alla fyra ställen i `gpm.py` (via
  `_ev_fuse_room`). Exporterande fas stryps aldrig för. Valfri marginal:
  `fuse_safety_margin_a` (standard 0 A, samma som tidigare). **Medvetet avsteg från
  FTW:** utan färsk Tibber-data faller den tillbaka på den gamla formeln istället
  för att stoppa all laddning. 17 tester (`tests/test_fuse_guard.py`), både
  aktivering och icke-aktivering.

- **Elmätaren är konfigurerbar (`power_meter:` i house_config.yaml).** Förut läste
  motorn en enda hårdkodad Tibber Pulse - alla andra installationer fick ingen
  nätmätning, alltså varken effektvakt, säkringsskydd eller solladdning. Nu: per fas
  (spänning + ström, t.ex. Tibber Pulse), en nettoeffekt-sensor, eller import/export
  (P1/HAN). Utan sektionen letas en Tibber Pulse upp automatiskt efter namnmönster
  (svenska/engelska namn), så befintliga hus fortsätter fungera. Timförbrukningen till
  effektvakten tas från mätarens sensor om den finns, annars integreras den ur
  nettoeffekten. Entitetsväljaren föreslår sektionen. Adressen i entitetsnamnen är
  borta ur motorns kod; den finns kvar i `config/examples/emil_house.yaml`, i den äldre
  Gecko-spadrivrutinen, i `ewapp` (spa/väder) och i `smartdashboard` (fasas ut).

- **Översikten lever: "Just nu"-flöde + dygnet timme för timme. Spabad och Elbil utökade.**
  Flödesbilden (`smartbox/live_flow.py`) visar bara det huset har - sol, nät, hus
  alltid, värmepump/varmvatten/spabad/bilar/batteri om de rapporterar - med prickar
  vars fart följer effekten och riktning för köp/sälj, och "varför" per enhet under.
  Tidslinjen (`smartbox/timeline.py`) visar 24 h uppmätt bakåt och planerat framåt:
  elpris, sol, värmepumpens kompressor/läge, spabadets värmning och varje bils
  laddning. Spabad: normal/max/Eco-temperaturer (max 40 °C, motorns säkerhetsgräns),
  "klart till" och 24 h-diagram. Elbil: laddplanen per kvart mot elpriset med
  batterinivå. Rättat: Elbil-sidan visade Teslas och Nissans effekt omkastat, "EV
  Laddning" visade bara den ena laddboxen och "planerat idag" var 4x för högt.
- **Buy Me a Coffee i README** (`.github/workflows/buy-me-a-coffee.yml`, låst till
  en exakt commit av akosbalasko/coffee-readme). Väntar på repo-hemligheten
  `BUY_ME_A_COFFEE_TOKEN`; utan den hoppar jobbet över sig själv. Pushar som bara rör
  README/ROADMAP/docs bygger inga Docker-bilder längre.

- **"Vad görs nu och varför" per enhet + SolarEdge via officiella integrationen.**
  Beslutstexten var förut gpm-loggens sista rad - nästan alltid effektvaktens "Peak
  Shaving är inaktiverat". Nu en mening per enhet (elbil, värmepump, varmvatten,
  spabad, sol, effekttak) med gpm.py:s egen förklaring, informationsrader bortfiltrerade
  (`smartbox/decision_summary.py`, sparas som `sensor_log.decision_summary` och som
  attributet `per_enhet` på `sensor.smartbox_beslut`). Visas överst på webbens Översikt
  och på appens Hem. SolarEdge: entitetsväljaren föreslår den officiella
  [SolarEdge Modbus](https://www.home-assistant.io/integrations/solaredge_modbus/)
  (HA 2026.10) via `generic_number`; den handbyggda drivrutinen bara när den äldre
  integrationens entitet finns. Exportgränsen skrivs sparsamt för att inte slita
  växelriktarens flashminne (`smartbox/solar_write_guard.py`).

- **Mobilappen i fem flikar + historik i webben och appen.** `ewapp`: Hem (Just nu /
  Härnäst, sol och nät live, besparing på en rad - bara för ägaren, även i servern -
  och ljusknappar), Bil, Hus, Plan (planen eller laddschemat) och Historik (Energi:
  summor Idag/7/30 dagar + effekt 24 h/7 d/30 d/1 år; Temperatur; Elpris). Ingen
  flik scrollar - verifierat på 390x844 och 360x640. Gamla flikval (Ljus, Energi,
  Schema, Grafer) pekas om. Webbens Historik-sida har samma energivy, loggen ligger
  kvar under. Data: `smartbox/energy_history.py` (tidsviktad energi ur sensor_log),
  delad av båda. Idén från FTW:s History-vy, egen implementation.

- **Besparingskort och planen i klartext (webdashboard, Översikt + Ekonomi).**
  Idéerna från [FTW](https://github.com/srcfl/ftw):s savings-kort och plan brief,
  egen implementation (ingen kod kopierad - FTW är AGPL). Besparingen är samma
  formel som den publika sidan, med dygn i svensk tid (`smartbox/savings.py`).
  Planen beskriver motorns egen plan: elbilens laddpass ur `ev_plan_slots` och
  värmepumpens grundläge per period enligt exakt samma prisregel som `gpm.py`
  (`smartbox/plan_brief.py`). 17 tester.

- Drivrutinsarkitektur kopplad till huvudstyrloopen (bil/laddare/värmepump/sol/spa)
  - genuint insticksbart, inte bara ett löfte.
- Entitetsväljare med auto-discovery (`webdashboard`, Inställningar-sidan).
- Publik sida med riktiga, verifierbara besparingssiffror.
- Bil-lås/luckor i webdashboard, med samma säkerhetsgräns som `ewapp`: ett eget
  `ew2`-omverifieringsflöde (lösenordet igen, 10 minuters fönster) innan
  ett lås-/luckokommando proxas vidare till `ewapp`:s riktiga Tesla-hantering
  (samma `_secure_ok`/`_unlock_fails`-spärr körs fortfarande där, bara anropad
  härifrån också) - inte en genväg runt säkerhetslagret.
