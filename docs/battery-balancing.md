# Behovsstyrd batteribalansering (#343)

EnergyWizard kan begära ett planerat balanseringsförsök när **färska laddnivåer
från minst två moduler** skiljer sig åt. Funktionen är avstängd som standard.
Den framtvingar inte en fulladdning var trettionde dag. Modulernas SOC-skillnad
är en indikation för planeringen, inte ett bevis på cellobalans eller ett
universellt tillverkarvillkor.

## Planering och skydd

När skillnaden har bestått under bekräftelsetiden lägger dygnsplaneraren in ett
krav på målnivå och sammanhängande hålltid. Den väljer lägsta modellerade
totalkostnad över kända priser, huslast, sol och elbilens plan; försöket behöver
inte ge lönsam arbitrage. Den vanliga optimeringen fortsätter fram till och efter
underhållet. `max_soc` är fortfarande vardagens laddtak; endast det begärda
underhållet får planera upp till `balance.target_soc`.

EW måste styra batteriet (`control: styr`), ha dygnsplan och kapacitet samt
verkligt stöd för både laddning och hålläge. Befintliga verifieringsspärrar för
drivrutiner gäller fortfarande. Funktionen ändrar **inte** växelriktarens eller
BMS:ens egna SOC-gränser. En installation vars egna gränser stoppar laddningen
kan därför inte slutföra försöket; EW kringgår inte dessa gränser.

Reserv, huvudsäkring, effekttak, gammal mätardata och befintliga regler för
elbilen går före underhållsplanen. `samarbete` och `av` ger inga batterikommandon.
Saknade eller mer än 120 sekunder gamla modulvärden stoppar underhållsplaneringen.
En tidigare upptäckt modul får inte försvinna ur jämförelsen. Alla moduler måste
ha hållit målnivån (0,5 procentenheters avrundningsmarginal) under hela hålltiden
för att EW ska registrera genomfört försök. Även en naturlig fulladdning räknas.
Detta bekräftar uppmätt SOC/hålltid, **inte** att BMS har rapporterat färdig
cellbalansering.

Begäran och senaste genomförande sparas lokalt. Omstart eller mätluckor nollställer
obevisad hålltid. En fast tidsgräns på 36 timmar hindrar att omplanering skjuter
försöket framåt för alltid. Om det inte går att genomföra inom kända priser
behålls vanlig planering och status visar uppskjutet. Ett försök som inte blir
klart inom 36 timmar avbryts utan att markeras färdigt. Nytt automatiskt försök
kräver både minimiintervallet och att skillnaden först har återgått till under
halva tröskeln under bekräftelsetiden. Det förhindrar återkommande fulladdningar
vid ett kvarstående fel. Tillfälligt försvunnen skillnad avbryter en väntande
begäran, men inte ett redan påbörjat försök.

## Telemetri och märken

- **Ferroamp MQTT (`driver: ftw`, `ftw.driver: ferroamp`)**: de befintliga
  `extapi/data/eso`-meddelandena ger separata ESO-ID:n, SOC och mottagningstid.
  Ingen ny Modbus-adress antas. Ett uttryckligt underhållskommando får passera
  Lua-drivrutinens normala 95 %-marginal för laddningsdispatch; ordinarie
  dispatch, effektgränser och BMS-skydd kvarstår.
- **Andra märken via Home Assistant**: ange jämförbara SOC-sensorer för moduler
  inom samma batterisystem i `module_entities`. Värdena ska vara procent
  (0–100) och ha `last_reported` eller `last_updated` med tidszon. Alla
  konfigurerade sensorer måste rapportera. Mappningen fungerar oberoende av
  märke, med en batteridrivrutin som faktiskt kan ladda och hålla.
- **Ferroamp Modbus och andra rena aggregatvärden**: systemets genomsnittliga
  SOC räcker inte för att upptäcka modulskillnad. EW hittar inte på register
  eller BMS-signaler. Den inbyggda Ferroamp-Modbus-drivrutinen saknar dessutom
  verifierat hålläge och kan därför inte utföra detta underhåll. Enbart
  spänningsskillnader eller en allmän BMS-varning tolkas inte automatiskt som
  behov av en 100 %-cykel.

Välj tröskel, målnivå och hålltid efter batteriets dokumentation och
installationsförutsättningar. Standardtröskeln 5 **procentenheter** följer
ZenAI-kodens ESO-indikation; den är inte en tillverkarcertifierad diagnos.
Standardvärdena 100 % / 120 minuter är konfigurerbara planeringsvärden, inte
generella skötselråd för alla batterikemier.

## Konfiguration

Lägg till i befintlig `battery:` i `house_config.yaml` efter att installationens
telemetri och ladd-/hållfunktion har verifierats:

```yaml
battery:
  # enabled, driver, anslutning och styrmappning som tidigare
  control: styr
  plan: true
  capacity_kwh: 10
  max_soc: 85
  balance:
    enabled: true
    spread_pct: 5             # procentenheter, standard 5
    confirm_minutes: 5       # 1–60, standard 5
    target_soc: 100           # 50–100; måste ligga över reservnivån
    hold_minutes: 120         # 15–240, standard 120; planeras i hela kvartar
    min_interval_days: 7      # 1–365, standard 7; ingen periodisk utlösare
    # Utelämna för Ferroamps inbyggda MQTT-telemetri.
    module_entities:
      - sensor.battery_module_1_soc
      - sensor.battery_module_2_soc
```

## Visning

Webben och mobilappen visar en informationsruta för balansering: väntar på
telemetri, bekräftar skillnad, begärt/schemalagt, pågår, pausat av övriga regler,
uppskjutet eller avbrutet. Under pågående underhåll förklarar den att vanlig
batteriplanering återupptas efteråt. Planens tidslinje och planklocka markerar
laddning/hålltid som balansering. Samma texter finns på svenska, engelska och
tjeckiska. Visningen av ett planerat pass är inte bevis på att enheten följt
kommandot; EW:s befintliga batteriföljning fortsätter kontrollera det.

## Verifiering

`tests/test_battery_balance.py` provar detektion, källålder, modulbortfall,
omstart, naturlig fulladdning, spärr mot upprepning, timeout, säkerhetsprioritet,
billigaste period jämfört med uttömmande sökning, sol, ogenomförbar horisont,
snapshot-replay, PostgreSQL-lagring, UI-underlag och den riktiga Ferroamp-Lua-koden
med inspelade meddelandeformer och isolerad transport. Det är inte ett prov mot
en verklig växelriktare/BMS. Ingen liveinstallation ändrades för denna funktion.
