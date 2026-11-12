# Batterier och växelriktare – vad EnergyWizard kan läsa och styra

Senast genomgången 2026-11-06. De 20 vanligaste husbatterierna och hybridväxelriktarna i Sverige och Norden, och hur
EnergyWizard pratar med var och en. Det finns tre vägar:

- **HA-förinställning**: Home Assistant-integrationen finns redan hos användaren. Installationsguiden känner igen den
  och fyller i styrningen själv (`smartbox/discovery.py`, `_battery_control_preset`). Lägesnamnen är integrationens
  egna och lästa i dess källkod, inte gissade.
- **FTW-drivrutin**: Sourcefuls Lua-drivrutin körs direkt mot enheten (Modbus TCP/HTTP/MQTT) utan HA-integration
  (`driver: ftw`, `smartbox/drivers/ftw_device.py`, 93 drivrutiner i `smartbox/ftw_drivers/`). Alltid läsande; styrning
  bara för verifierade drivrutiner eller med `control_unverified: true`.
- **Egen drivrutin**: skriven i EnergyWizard (Ferroamp).

"Verifierad" betyder provad på riktig hårdvara hos en användare. Allt annat är provat mot källkod och tester, och
bör köras i skuggläge först.

| # | Märke / modell | HA-integration | Läsa | Styra via HA | FTW-drivrutin | Status |
|---|---|---|---|---|---|---|
| 1 | Huawei SUN2000 + LUNA2000 | wlcrs/huawei_solar | ✅ | ✅ tjänster (tvångsladdning/-urladdning, 30 min åt gången) | `huawei` (läsande, styrning avstängd hos FTW) | Ny 2026-11-05, ej verifierad |
| 2 | SolarEdge + Home Battery / BYD (StorEdge) | solaredge_modbus_multi | ✅ | ✅ Storage Control/Command Mode | `solaredge` (sol, mätare, exportgräns) | Ny 2026-11-05, ej verifierad |
| 3 | Fronius GEN24 + BYD HVS | redpomodoro/fronius_modbus | ✅ | ✅ Storage Control Mode | `fronius`, `fronius_api` | Förinställning sedan 2026-11-03 |
| 4 | Sungrow SH-RT/RS + SBR | mkaiser/Sungrow-SHx (modbus-yaml) | ✅ | ✅ EMS mode + forced charge/discharge | `sungrow` (styrning finns i FTW) | Ny 2026-11-05, ej verifierad |
| 5 | Growatt SPH/MOD + ARK | wills106/solax-modbus (Growatt-plugin) | ✅ | ✅ Time 1 Mode | `growatt` | Förinställning |
| 6 | Solax X1/X3 Hybrid G4–G6 + Triple Power | wills106/solax-modbus | ✅ | ✅ Charger Use Mode + Manual Mode | `solax` | Förinställning |
| 7 | Solax Gen2 (SK-SU) | wills106/solax-modbus | ✅ | ✅ (Self Use / Back Up / Force Time Use) | – | **Verifierad** (#86, två växelriktare) |
| 8 | GoodWe ET/EH + Lynx | HA:s inbyggda goodwe | ✅ | ✅ Inverter operation mode (eco_charge/eco_discharge) | `goodwe` | Ny 2026-11-05, ej verifierad |
| 9 | FoxESS H3 + ECS | nathanmarlor/foxess_modbus, FoxESS Cloud | ✅ | ✅ Work Mode + Force Charge/Discharge | `foxess_h3_smart` | Förinställning |
| 10 | Solis RHI / S6 hybrid | Pho3niX90/solis_modbus | ✅ | ✅ RC Force Charge/Discharge | `solis`, `solis_string` | Förinställning |
| 11 | Ferroamp EnergyHub + ESO/ESM | (egen) | ✅ | ✅ egen Modbus-drivrutin | `ferroamp`, `ferroamp_modbus` | Egen drivrutin |
| 12 | Tesla Powerwall 2/3 | teslemetry / tesla_fleet | ✅ | ⚠️ bara självförbrukning ↔ backup (ingen tvingad urladdning i Teslas API) | – | Ny 2026-11-05 |
| 13 | Deye / Sunsynk | davidrapan/ha-solarman | ✅ | – (styrs via FTW-vägen) | `deye` (har styrning) | Styrning via `driver: ftw` (val i guiden), ej verifierad |
| 14 | SMA Sunny Tripower Smart Energy / Sunny Boy Storage | sma / pysmaplus | ✅ | ⏳ | `sma`, `sma_pv` (ingen styrning) | Läsning – styrning kräver SMA:s Modbus-register, planeras |
| 15 | Victron (ESS, Cerbo GX) | sfstar/hass-victron | ✅ | ✅ ESS-börvärde för nätet (+ ladda, − ladda ur) | `victron`, `victron_mqtt` | Ny 2026-11-06, ej verifierad |
| 16 | Sigenergy SigenStor | TypQxQ/Sigenergy-Local-Modbus | ✅ | – (styrs via FTW-vägen) | `sigenergy` (har styrning) | Styrning via `driver: ftw` (val i guiden), ej verifierad |
| 17 | Pixii PowerShaper / Home | – (ingen HA-integration) | ✅ via FTW | – | `pixii` (har styrning), `pixii_pv` | Styrning via `driver: ftw` (val i guiden), ej verifierad |
| 18 | Kostal Plenticore + BYD | HA:s inbyggda kostal_plenticore | ✅ | ⚠️ bara håll (lägsta laddnivå = nuvarande) | `kostal` | Ny 2026-11-06, ej verifierad |
| 19 | Alpha ESS SMILE | alphaess (moln) | ✅ | ⏳ (bara molnschema med anropsgränser) | `alphaess` | Läsning |
| 20 | Sonnen | weltmeyer/ha_sonnenbatterie | ✅ | ✅ manuellt läge + laddning/urladdning (tjänster) | `sonnen` | Ny 2026-11-06, ej verifierad |
| – | Enphase IQ Battery | HA:s inbyggda enphase_envoy | ✅ | ⚠️ bara självförbrukning ↔ full backup | – | Ny 2026-11-05 |
| – | Emaldo | – (ingen integration) | ❌ | ❌ | – | Saknas, väntar på API |
| – | HomeWizard Plug-In Battery | HA:s inbyggda homewizard | ✅ | ✅ laddstrategi | – | Förinställning |
| – | Solinteg MHT/MHS | – (FTW direkt; guiden namnger `solinteg` när märket syns i HA) | ✅ via FTW | – | `solinteg` (har styrning) | Ej verifierad på hårdvara (#219). Styrning är av tills användaren kryssar i den. |

## FTW-drivrutinerna mot Sourcefuls simulator (GitHub Actions, `simulator.yml`)

Varje push som rör FTW-delarna kör drivrutinerna genom vår Lua-brygga mot srcfl/device-simulator (simulerat hus:
sol 3 kW, batteri 10 kWh på 50 %). Resultat 2026-11-06:

| Drivrutin | Läsning | Styrning (ladda 2 kW / ladda ur 2 kW) |
|---|---|---|
| sungrow | ✅ | ✅ följer båda |
| huawei | ✅ | – avstängd i FTW:s drivrutin (avsiktligt) |
| solaredge | ✅ (sol) | – inget batteri i simulatorns modell |
| solis, deye, pixii | ✅ | ⏳ kommandot godtas, men urladdningen syns inte inom 45 s – utreds |
| sma | ✅ | ❌ kommandot avvisas |
| fronius | ❌ solen läses som 0 W (känd avvikelse) | ❌ |

Simulatorverifiering räcker inte för att slå på styrning hos användare – det kräver fortfarande en riktig enhet –
men Sungrow är nu först i kön för `FTW_CONTROL_VERIFIED`.

## Så kommer vi vidare

1. **Verifiering**: varje "ej verifierad" behöver en användare som kör i skuggläge några dygn och sedan slår på
   styrningen och bekräftar att laddning, urladdning och återgång fungerar. Betatestare med utrustningen:
   Huawei LUNA (#144), Solax + Emaldo (#135), Sungrow/GoodWe/SolarEdge – efterlys i Discord.
2. **FTW-styrning**: när en FTW-drivrutin provats med styrning på riktig hårdvara läggs den in i `FTW_CONTROL_VERIFIED`.
   Sungrow, Sonnen, Victron och SMA har styrvägar i FTW – de är först i kön.
3. **Deye/Sunsynk och Sigenergy via HA**: kräver att man skriver växelriktarens TOU-program eller Remote EMS-register.
   Görs när en testare finns (fel här kan låsa batteriet i fel läge).
