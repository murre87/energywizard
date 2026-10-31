# Roadmap

Inte löften om datum - bara vad som är nästa rimliga steg och varför, så det är
tydligt vad som redan är beslutat och vad som väntar på mer underlag.

## Övervägs, väntar på fler verkliga hus att verifiera mot

- **Inbyggd husbatteri-drivrutin** (Powerwall, GivEnergy, Huawei Luna m.fl.).
  Ett riktigt elbatteri är snabbt och konkurrerar direkt med sol/nät/elbilsladdning
  om samma watt - en genuint annan optimeringsfråga än husets termiska tröghet som
  redan styrs idag. Byggs när fler betatestare faktiskt har ett husbatteri att
  testa mot, inte i förväg på gissningar. Fram tills dess: kör
  [Predbat](https://github.com/springfall2008/batpred) parallellt - se
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

- **Delad ML-modellträning på poolad data** från flera hus (bättre solprognoser,
  prismönster) - kräver den opt-in-telemetritjänst som redan är designad
  (`smartbox/telemetry.py`, pausad) men inte färdigkopplad än.

## Redan klart

- Drivrutinsarkitektur kopplad till huvudstyrloopen (bil/laddare/värmepump/sol/spa)
  - genuint insticksbart, inte bara ett löfte.
- Entitetsväljare med auto-discovery (`webdashboard`, Inställningar-sidan).
- Publik sida med riktiga, verifierbara besparingssiffror.
