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

- **Fler värmepumpsmärken** (NIBE, IVT, CTC, Mitsubishi, Viessmann m.fl.) -
  arkitekturen (`smartbox/drivers/heatpump.py`) är byggd för det, men varje
  märke kräver en egen, verifierad implementation - bidrag välkomna.
  NIBE är redan sökbar via Home Assistant-skanningen (`HEATPUMP`-regexen i
  `smartbox/discovery.py` matchar den), flaggas bara `driver_known: False`
  tills en riktig drivrutin finns. Anslutningssättet varierar med modell -
  äldre pumpar pratar RS485 (t.ex. via [NibePi](https://energy.anerdins-iot.se/)
  + MQTT till HA), nyare S-serie-pumpar har en inbyggd Modbus TCP-server med
  en helt annan registerkarta än Husdata/Thermia - kräver verifiering mot en
  riktig pump av varje typ, inte gissad kod.

- **Balboa-spabad som egen, verifierad drivrutin.** `discovery.py` pekar redan
  "balboa" mot `GeckoSpaDriver` (kommentar: "byggd mot Balboa-liknande
  styrsystem") - men det är ett ANTAGANDE, aldrig verifierat mot ett riktigt
  Balboa-system (bara Gecko). HA:s officiella `balboa`-integration exponerar
  sannolikt en annan entitetsform än Gecko in.touch2 - samma risk som
  Gecko-drivrutinens två tidigare misslyckade generaliseringsförsök denna
  session. Byggs separat, verifierat, den dag en riktig Balboa-testare finns
  - inte en snabb omskrivning av antagandet.

- **Delad ML-modellträning på poolad data** från flera hus (bättre solprognoser,
  prismönster) - kräver den opt-in-telemetritjänst som redan är designad
  (`smartbox/telemetry.py`, pausad) men inte färdigkopplad än.

## Redan klart

- Drivrutinsarkitektur kopplad till huvudstyrloopen (bil/laddare/värmepump/sol/spa)
  - genuint insticksbart, inte bara ett löfte.
- Entitetsväljare med auto-discovery (`webdashboard`, Inställningar-sidan).
- Publik sida med riktiga, verifierbara besparingssiffror.
