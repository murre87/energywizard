# Roadmap

Inte löften om datum - bara vad som är nästa rimliga steg och varför, så det är
tydligt vad som redan är beslutat och vad som väntar på mer underlag.

## Övervägs, väntar på fler verkliga hus att verifiera mot

- **Automatiserade laddnings-/urladdningsbeslut för husbatteri.** Ett riktigt
  elbatteri är snabbt och konkurrerar direkt med sol/nät/elbilsladdning om
  samma watt - en genuint annan optimeringsfråga än husets termiska tröghet
  som redan styrs idag, och ingen betatestare har ännu ett riktigt batteri
  att verifiera besluten mot. `gpm.py` fattar därför medvetet INGA beslut om
  batteriet än. **Drivrutinslagret finns dock redan** (`drivers/battery.py`/
  `battery_generic.py`, upptäcks av entitetsväljaren) - läser SOC/effekt och
  kan sätta ett läge via valfri `select`-entitet, samma generiska
  entitetsstyrning som [Predbat](https://github.com/springfall2008/batpred)
  själv bygger på. Kör gärna Predbat parallellt tills vidare - se
  [kunskapsbanksartikeln](https://murre87.github.io/energywizard/kunskapsbank/husbatteri.html).

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
  - **Steg 2, dubbelriktad samplanering (inte byggt, större):** publicera
    EnergyWizards planerade laster (t.ex. elbilens laddfönster, kommande
    värmepumpsbeslut) som en HA-sensor Predbat kan läsa in som extra
    förväntad last i sin egen prognos - den riktiga "pratar med varandra"-
    biten. Kräver dels en ny, enkel exportsensor i EnergyWizard, dels att
    Predbat faktiskt stödjer att läsa in externa förväntade laster på ett
    stabilt sätt mellan versioner - overifierat, ingen betatestare med
    batteri + Predbat ännu att prova mot. Avsiktligt uppskjutet tills en
    sådan finns.

- **OCPP-laddare via Home Assistants egen OCPP-integration - kod+regex klar,
  overifierad mot riktig laddare.** [lbbrhzn/ocpp](https://github.com/lbbrhzn/ocpp)
  (HACS, mogen, stödjer 1.6J/2.0.1/2.1) kör OCPP-servern inuti Home Assistant
  och exponerar en `switch` (`*_charge_control`) + `number`
  (`*_maximum_current`) - samma entitetsformer `GenericChargerDriver` redan
  läser/skriver. `smartbox/discovery.py` matchar nu entitets-ID:ets suffix
  (inte märkestext - laddarens egen tillverkarsträng, inte "OCPP", syns i HA)
  och föreslår `generic`-drivrutinen automatiskt, med ett nytt regressionstest
  (`tests/test_discovery.py`). Mockat/syntetiskt verifierat, ALDRIG kört mot
  en riktig OCPP-laddare.

- **Fler värmepumpsmärken** (IVT, CTC, Mitsubishi, Viessmann m.fl.) -
  arkitekturen (`smartbox/drivers/heatpump.py`) är byggd för det, men varje
  märke kräver en egen, verifierad implementation - bidrag välkomna.

- **NIBE S-serie: drivrutin byggd, overifierad mot riktig hårdvara.**
  `drivers/heatpump_nibe_local.py` (`nibe_local` i
  `HEAT_PUMP_DRIVER_REGISTRY`) pratar S-seriens (S735/S1255/S1155/S320 m.fl.)
  lokala REST-API - HTTPS-port 8443, Basic-auth, certifikatet PINNAS (SHA-256-
  fingeravtryck, TLS-verifiering stängs aldrig av) - byggd mot
  [srcfl/ftw](https://github.com/srcfl/ftw)s
  [nibe-local-dokumentation](https://github.com/srcfl/ftw/blob/master/docs/nibe-local.md)
  och den faktiska drivrutinskällan (`srcfl/device-drivers`), inte gissad.
  **Ärlig avgränsning:** bara anslutning/enhetsidentifiering + en rå
  datapunktsläsning är bekräftad mot källan - vi har INGEN bekräftad karta
  mellan våra normaliserade fält (`indoor_temp`/`outdoor_temp`/driftläge) och
  NIBE:s faktiska registernummer för dem (källan dokumenterar bara register
  2107/2109, en solöverskott-funktion, inget annat). `read_sensors()`
  returnerar därför bara rådata (antal datapunkter), och ALLA
  `set_*`-metoder returnerar medvetet `False` - exakt samma princip som
  `GenericClimateHeatPumpDriver` redan använder för Husdatas
  registernivå-funktioner. Ansluts via `.env` (`NIBE_LOCAL_HOST`/
  `_USERNAME`/`_PASSWORD`/`_TLS_PIN_SHA256`), inte auto-upptäckt av
  entitetsväljaren (den pratar direkt med pumpen, aldrig via HA - samma skäl
  som Husdata/Thermia inte är HA-upptäckt). Mockade tester bevisar att koden
  anropar rätt endpoints med rätt fält - ALDRIG kört mot en riktig pump. Har
  du en NIBE S-serie-pump? Hör av dig, det är precis den sortens verkliga
  installation som behövs för att identifiera de saknade registren och
  bekräfta resten.

- **NIBE/Bosch/Atlantic/Daikin via myUplink (NIBE:s delade molnplattform) -
  inte byggt, möjligt högre värde än den lokala REST-drivrutinen ovan.**
  [FTW:s enhetskatalog](https://srcfl.github.io/device-drivers/drivers.json)
  listar en `myuplink`-drivrutin som pratar molnbaserat (OAuth) med
  myUplink - NIBE:s officiella plattform, delad av flera märken (Bosch,
  Atlantic, Daikin bekräftat i katalogen). EN drivrutin där skulle alltså
  kunna täcka flera värmepumpsmärken samtidigt, istället för en lokal
  REST-/Modbus-drivrutin per märke. Avvägningen att vara ärlig om: det är en
  genuint annan ansats än allt annat i EnergyWizard - kräver ett molnkonto/
  OAuth-autentisering, inte lokalt-first som resten av projektet medvetet
  prioriterar. Inget byggt än - nästa, högre prioriterade steg för
  värmepumpsstöd efter att NIBE-lokal-drivrutinen ovan är verifierad eller
  övergiven.

- **Termisk säkringsmodell för effektvakten (Prio 10), inte byggd.**
  [FTW:s `safety.md`](https://github.com/srcfl/ftw/blob/master/docs/safety.md)
  beskriver en mer nyanserad modell för elbilsladdning än vår nuvarande:
  kvadrerad fasström lågpassfiltrerad med 60 s tidskonstant, stryper vid
  verklig överbelastning (eller omedelbart över 1,2× säkringens märkvärde)
  men tillåter korta toppar, med separat, längre återhämtningsfönster (ingen
  ökning inom 20 s efter en strypning). Vår nuvarande `gpm.py`-logik (Prio
  10) bygger på energibudget per timme + direkt tillgängliga-ampere-avdrag -
  enklare, men stryper troligen onödigt ofta vid korta effekttoppar som en
  riktig säkring ändå skulle klara. Värt att undersöka, ingen brådska -
  nuvarande modell är säker, bara möjligen för försiktig.

- **Balboa-spabad: drivrutin byggd, väntar på verifiering mot riktig
  hårdvara.** `drivers/spa_balboa.py` finns nu - byggd mot HA:s officiella
  `balboa`-integrations DOKUMENTERADE entitetsformer (climate/select/switch/
  fan), inte en gissad protokolltolkning som den tidigare Gecko-genvägen var.
  Fortfarande aldrig körd mot ett riktigt Balboa-system (bara mockade
  tester) - har du ett Balboa-spabad? Hör av dig, det är precis den sortens
  verkliga installation som behövs för att bekräfta den.

- **Delad ML-modellträning på poolad data** från flera hus (bättre solprognoser,
  prismönster). **Telemetrilagret finns nu och är publikt nåbart**
  (`smartbox/telemetry.py`, strikt opt-in och av som standard - skickar bara
  hashad husidentifierare, aktiva drivrutinkategorier, feltyp och version,
  ingen sensorhistorik), på
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

## Redan klart

- **"Lägg till i Home Assistant"-knapp för Supervisor/HAOS-användare**
  (`ha-addon/smartbox/`, `repository.yaml`, samma `my.home-assistant.io`-
  genväg som [EMHASS](https://github.com/davidusb-geek/emhass)). Paketerar
  idag BARA huvudmotorn (`smartbox`), inte `webdashboard`/`ewapp` - de kräver
  fortfarande docker-compose-vägen. Postgres bundlas lokalt i
  tilläggscontainern (ett enkelt startskript, inte s6-overlay - dokumenterat
  avsteg i Dockerfile-kommentaren). **Verifierat:** bygger och startar
  fristående i Docker, Postgres initieras och databasen skapas, huvudloopen
  kör utan att krascha, och koden tar rätt väg (`http://supervisor/core/api`)
  när `SUPERVISOR_TOKEN` finns. **Overifierat:** har aldrig körts mot en
  riktig HAOS/Supervisor-installation - "Lägg till repository"-flödet,
  Supervisorns egen validering av `config.yaml`, och den riktiga
  `homeassistant_api`-proxyn är alla otestade här. Första installationens
  engångs-notis pekar fortfarande mot en webdashboard-adress som inte finns
  i den här driftformen - känd brist tills gränssnitten också paketeras.

- Drivrutinsarkitektur kopplad till huvudstyrloopen (bil/laddare/värmepump/sol/spa)
  - genuint insticksbart, inte bara ett löfte.
- Entitetsväljare med auto-discovery (`webdashboard`, Inställningar-sidan).
- Publik sida med riktiga, verifierbara besparingssiffror.
- Bil-lås/luckor i webdashboard, med samma säkerhetsgräns som `ewapp`: ett eget
  `ew2`-omverifieringsflöde (lösenordet igen, 10 minuters fönster) innan
  ett lås-/luckokommando proxas vidare till `ewapp`:s riktiga Tesla-hantering
  (samma `_secure_ok`/`_unlock_fails`-spärr körs fortfarande där, bara anropad
  härifrån också) - inte en genväg runt säkerhetslagret.
