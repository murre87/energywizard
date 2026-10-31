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
  **Säkerhetsmönster värt att återanvända när det väl byggs:** [FTW](https://github.com/srcfl/ftw)s
  opt-in-skrivväg för batteri/solöverskott har en dead-man switch (slutar
  skriva om den inte hör av sig), en tydlig återgång till standardläge, och
  en uppstarts-sweep som städar bort gamla/föräldralösa kommandon - exakt den
  sortens skyddsnät ett framtida batteribeslut i `gpm.py` behöver, oavsett om
  vi återanvänder FTW:s kod eller bara mönstret.

- **Egen OCPP-server för laddare, istället för en drivrutin per märke.**
  [FTW](https://github.com/srcfl/ftw) har en inbyggd OCPP 1.6J/2.0.1-server -
  vilken OCPP-kompatibel laddare som helst fungerar direkt, ingen
  märkesspecifik drivrutin behövs. Vår `ChargerDriver`-arkitektur
  (`smartbox/drivers/charger*.py`) kräver idag en drivrutin per märke (Easee,
  generisk HA-switch/number) - en OCPP-server skulle täcka betydligt fler
  laddare på en gång. Inget påbörjat, men värt en egen utredning: hur mycket
  jobb är en minimal OCPP 1.6J-server jämfört med nästa märkesspecifika
  drivrutin, och hamnar den bättre eller sämre placerad än att luta sig mot
  HA:s egna OCPP-integrationer (om sådana finns och är tillräckligt generiska)?

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
  prismönster) - kräver den opt-in-telemetritjänst som redan är designad
  (`smartbox/telemetry.py`, pausad) men inte färdigkopplad än.

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
