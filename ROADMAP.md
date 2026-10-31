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

- **OCPP-laddare via Home Assistants egen OCPP-integration, ingen egen
  server.** [FTW](https://github.com/srcfl/ftw) kör en egen inbyggd
  OCPP 1.6J/2.0.1-server, men vi behöver inte bygga om det - det finns redan
  en mogen, aktivt underhållen HA-integration som gör exakt samma sak:
  [lbbrhzn/ocpp](https://github.com/lbbrhzn/ocpp) (HACS, stödjer
  1.6J/2.0.1/2.1) kör OCPP-servern inuti Home Assistant och exponerar en
  `switch` ("Charge Control") + `number` (`number.<cpid>_maximum_current`) -
  samma entitetsformer som vår befintliga `GenericChargerDriver` redan läser/
  skriver. Borde alltså redan fungera mot vilken OCPP-laddare som helst utan
  ny drivrutinskod - återstår bara att verifiera mot en riktig OCPP-laddare,
  och eventuellt lägga till entitetsnamnet i `discovery.py` så
  entitetsväljaren känner igen och föreslår den.

- **Fler värmepumpsmärken** (NIBE, IVT, CTC, Mitsubishi, Viessmann m.fl.) -
  arkitekturen (`smartbox/drivers/heatpump.py`) är byggd för det, men varje
  märke kräver en egen, verifierad implementation - bidrag välkomna.
  NIBE är redan sökbar via Home Assistant-skanningen (`HEATPUMP`-regexen i
  `smartbox/discovery.py` matchar den), flaggas bara `driver_known: False`
  tills en riktig drivrutin finns. Anslutningssättet varierar med modell -
  äldre pumpar pratar RS485 (t.ex. via [NibePi](https://energy.anerdins-iot.se/)
  + MQTT till HA) - kräver verifiering mot en riktig pump av varje typ, inte
  gissad kod. **Nyare S-serie-pumpar (S735/S1255/S1155/S320 m.fl.) har en
  lokal REST-API, inte rå Modbus TCP** - rättad slutsats efter att ha läst
  [srcfl/ftw](https://github.com/srcfl/ftw)s
  [nibe-local-dokumentation](https://github.com/srcfl/ftw/blob/master/docs/nibe-local.md):
  HTTPS-port 8443, aktiveras i installatörsmeny 7.5, certifikatet pinnas
  (SHA-256-fingeravtryck) istället för att verifieringen stängs av, ~980
  datapunkter med Modbus-registernummer som metadata. Deras egen drivrutin är
  medvetet read-only - en opt-in skrivväg finns bara för solöverskott
  (register 2107/2109), inte generell styrning. Bra konkret referens för en
  framtida EnergyWizard-drivrutin mot S-serien, men fortfarande overifierad
  mot en riktig pump här.

- **Balboa-spabad: drivrutin byggd, väntar på verifiering mot riktig
  hårdvara.** `drivers/spa_balboa.py` finns nu - byggd mot HA:s officiella
  `balboa`-integrations DOKUMENTERADE entitetsformer (climate/select/switch/
  fan), inte en gissad protokolltolkning som den tidigare Gecko-genvägen var.
  Fortfarande aldrig körd mot ett riktigt Balboa-system (bara mockade
  tester) - har du ett Balboa-spabad? Hör av dig, det är precis den sortens
  verkliga installation som behövs för att bekräfta den.

- **Delad ML-modellträning på poolad data** från flera hus (bättre solprognoser,
  prismönster). **Telemetrilagret finns nu** (`smartbox/telemetry.py`,
  strikt opt-in och av som standard - skickar bara hashad husidentifierare,
  aktiva drivrutinkategorier, feltyp och version, ingen sensorhistorik) och
  samlartjänsten (`telemetry-collector/`) är byggd och testad lokalt - men
  INTE publikt nåbar än, behöver en domän/reverse proxy (samma mönster som
  `ha-gateway`) innan betatestares instanser kan skicka in något. Själva den
  poolade modellträningen är fortfarande inte byggd - det här är bara
  grunden som data kan börja samlas på.

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

- **"Lägg till i Home Assistant"-knapp för Supervisor/HAOS-användare** (samma
  `my.home-assistant.io`-genväg som [EMHASS](https://github.com/davidusb-geek/emhass)
  visar på sin egen GitHub-sida). Kräver riktig Supervisor-tilläggspaketering
  (`config.yaml`/`repository.yaml` i ett eget tilläggsrepo) som inte finns än -
  den befintliga `SUPERVISOR_TOKEN`-hanteringen i `homeassistant.py` är bara en
  kodnivå-anpassning, inte paketering. Avsiktligt uppskjutet, inget beslutat
  datum.

- **Bil-lås/luckor i webdashboard.** Finns i mobilappen `ewapp` (kräver en
  separat lösenords-omverifiering, `ew2`-flödet, innan ett lås-/luckokommando
  går igenom), men webdashboard fick INTE den kontrollen när resten av sidorna
  byggdes klara - en säkerhetsgräns av den här sorten förtjänar en egen, noga
  testad implementation i webdashboard, inte något som hastas in i samma
  omgång som vanliga skrivkontroller. Avsiktligt uppskjutet.

## Redan klart

- Drivrutinsarkitektur kopplad till huvudstyrloopen (bil/laddare/värmepump/sol/spa)
  - genuint insticksbart, inte bara ett löfte.
- Entitetsväljare med auto-discovery (`webdashboard`, Inställningar-sidan).
- Publik sida med riktiga, verifierbara besparingssiffror.
