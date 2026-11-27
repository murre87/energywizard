# Ändringar

❤️ EnergyWizard är gratis och öppet. Om det sparar pengar hemma hos dig kan du hålla det så med en sponsring (runt 10 USD i månaden räcker långt): https://github.com/sponsors/murre87

## 1.2.189 (2026-11-27)
- **Kort för varmvatten och spabad i Home Assistant (#558).** Ett nytt kort visar tankens temperatur, badets temperatur, nästa badtid och om uppvärmningen är planerad. Under en badtid står det att badet hålls varmt och när den slutar. Inom 36 timmar planerar EnergyWizard uppvärmningen inför badtiden. Längre bort planeras den inte än, och en tid som saknas visas inte som noll. Kortet läser bara.

## 1.2.182 (2026-11-27)
- **Mindre elpatron (tillsats) i värmen utan att huset blir kallare.** Analys av veckan: varje gång tillsatsen gick hade rumsåterkopplingen satt börvärdet till 23-25 °C, vilket ger en beräknad framledning på 50-55 °C medan kompressorn bara levererar 43-47 °C. Gradminuterna rasar mot -1190 och elpatronen kopplas in. Mätt över 30 dygn gav börvärde 21 4 % tillsats, 22 10 % och 23 82 %, medan framledningen var densamma. Nu (1) lär sig EnergyWizard varje dygn ur loggen högsta börvärdet pumpen klarar utan tillsats vid aktuell utetemperatur (lärt kapacitetstak, bara med rumsåterkoppling på), och (2) gradminutvakten gäller i alla lägen: vid gradminuter under -600 sänks börvärdet så att pumpen hämtar sig, om de kallaste rummen har marginal till golvet. Gränsen kan ändras med `heat_aux_guard_dm`.
- **Tillsatsen senaste 7 dagarna syns överst på Värmepump-fliken** (tid, uppskattad energi och kostnad), och i appen under Värme inne.
- **Startsidan visar vad som sparats sedan EnergyWizard startade.** En ny period "Totalt" vid sidan av Idag, 7 dagar och Månad, och en rad "Sparat sedan start" under siffran, i appen och webben, för alla installationer (samma formel som övrigt).
- **Publika sidans besparingssiffror uppdateras igen (#616).** Den nattliga publiceringen pushade från driftkatalogen (en annan gren) och avvisades varje natt sedan 13 november. Den går nu via en egen ren klon.

## 1.2.181 (2026-11-27)
- **Veckobrevet kommer från "EnergyWizards skapare".** Avsändarnamnet i veckobrevet och i bekräftelsemejlet är nu "EnergyWizards skapare", i stället för en funktionsadress. Texten längst ner säger redan att det är skaparen som är personuppgiftsansvarig.

## 1.2.180 (2026-11-24)
- **Återbetalning av solcellerna, under Solceller (#599, #602).** Se hur mycket solcellerna sparat och tjänat månad för månad, år för år och totalt, hur många procent av anläggningen som är betald och hur lång tid som återstår. Nyttan är besparingen på egenanvänd el (elpris, påslag, överföring och energiskatt) plus intäkten för såld el (med nätnytta) plus skattereduktionen, som räknas till och med ett slutdatum du anger (2025-12-31 i Sverige). Fasta avgifter och effektavgift räknas inte. Du anger vad anläggningen kostade och när den startade. EnergyWizard räknar med sina egna mätvärden, minut för minut, med dina elpris- och avgiftsinställningar. För tiden innan kan du läsa in månadsuppgifter från en CSV-mall (knappen **Ladda ner mall**), och en månad du skrivit in går alltid före de egna mätvärdena. Färdiga månader sparas och ändras inte när du senare ändrar avgifterna. Solens och nätets mätare avviker några procent från växelriktaren och nätägaren, och egenanvänd el är skillnaden mellan dem, så EnergyWizard kalibrerar mot de månader du skrivit in (minst tre) och säger det på sidan. Tid kvar räknas på nyttan de senaste 12 månaderna.

## 1.2.179 (2026-11-24)
- **Veckobrev med nyheter, om du vill (valfritt).** En liten rad längst ner på appens första sida (och Inställningar › Appen, installationsguiden och System på webben) där du kan skriva in din e-postadress för att få en kort sammanfattning av nyheterna i EnergyWizard varje torsdag kl 11. Du bekräftar via ett mejl och kan avsluta med länken i varje brev eller i appen. Adressen används bara till veckobrevet, lämnas inte vidare, raderas när du avslutar och kopplas inte till telemetrin. Raden går att klicka bort. Veckobreven ligger också som en egen flik, **Nyheter**, i appen och webben för alla (även familj och gäst), så att du kan läsa dem utan att anmäla dig. Mejlet kommer på svenska, engelska eller tjeckiska efter appens språk. Se `newsletter/README.md`.

## 1.2.178 (2026-11-24)
- **Kupévärme med två tider per dag och olika tider varje veckodag**, som laddschemat. Till exempel morgon kl 06:45 och hemresa från jobbet kl 16:30, och en annan tid på onsdagar. I webben under Elbil och i appen under Planen finns sju rader med två tider vardera (på/av och klockslag), en knapp "Samma som måndag alla dagar", och temperatur och "Håll varm" som gäller bilen. Hålltiden räknas från varje tid. Befintliga inställningar flyttas över automatiskt: den gamla tiden gäller som första tid alla dagar (#598).

## 1.2.177 (2026-11-24)
- **Håll varm fungerar även utan laddkabel.** En urdragen kabel avslutar inte längre hålltiden, så värmen kan hållas medan du hämtar bilen. Hålltiden avslutas bara när bilen flyttas från huset.
- **Kupévärmen räknar ut när den ska starta så att bilen är varm vid din tid.** Förut en fast tid ur utetemperaturen. Nu lär sig EnergyWizard hur många minuter per grad varje bil behöver (ur bilens egna värmepass i loggen) och räknar på hur kall bilen är just då, så en kall bil startar tidigare än en ljummen. Bilens kupétemperatur kan vara gammal, så den kapas till högst 5 grader över utetemperaturen. Har bilen för få mätbara värmepass används den gamla grundmodellen. Loggen visar hur lång tid som behövs och varför (#598).

## 1.2.176 (2026-11-24)
- **Håll bilen varm en vald tid efter sluttiden (kupévärme).** Ny inställning per bil, "Håll varm efter tiden" (0 minuter till 6 timmar, av som standard), i webben under Elbil och i appen under Planen. Är bilen varm kl 06:45 men du kommer kl 07:10 värmer EnergyWizard igen när kupén svalnat mer än en grad under måltemperaturen, och stänger av den när den är varm. Hålltiden avslutas när du hämtat bilen: när laddkabeln dras ur efter att den varit inkopplad, eller när bilen flyttas från huset. Bilar som aldrig kopplas in avslutas inte av en signal utan håller på hela tiden. En sovande bil kan visa gammal kupétemperatur, då startar inte värmen igen (#598).

## 1.2.175 (2026-11-24)
- **Bilens laddnivå: 12 V-batteriet väljs inte längre före traktionsbatteriet.** Kia och Hyundai har både "Car battery level" (12 V) och "EV battery level" (laddnivån), och guiden kunde ta fel. Namn som 12 V, auxiliary och car battery går sist, och namn som EV battery eller state of charge går först (#596).
- **Nätverksfel mot Home Assistant i styrfunktionerna är varningar, inte fel.** När HA var nere, startade om eller hade en ogiltig adress skrevs ❌ för spabadets plugg, Gecko-temperatur, SolarEdge-gräns m.fl., och varje sådant blev ett automatiskt GitHub-ärende (#588-#595). Nu är det ⚠️. HTTP-fel som 401 och 500 är fortfarande fel.

## 1.2.174 (2026-11-23)
- **Emaldo-förinställning (ny, ej provad på riktigt batteri).** Installationsguiden känner igen Emaldo-batterier via `wertigpar/ha-emaldo` och föreslår styrning med integrationens 15-minuterspass (`emaldo.set_slot_range`, ladda mot 100 % eller ladda ur), omskrivet var femte minut. Slutar EnergyWizard skriva tar batteriets eget schema över efter högst 30 minuter. Batterieffektens tecken (plus = urladdning) och nätmätaren (`power_store_grid_power`, inte husets last) väljs rätt. Börja i skuggläge. Tack till testaren i #580.

## 1.2.173 (2026-11-23)
- **Tillsatsen syns i mobilappen.** På Hus-sidan, under Värme inne, visas en röd rad när värmepumpen går på tillsats (steg, procent och hur länge den gått idag), och annars hur många minuter den gått idag. Bara för pumpar som rapporterar tillsatsen (Thermia Diplomat via Husdata).
- **Värmepumpsrutan i flödesbilden (Just nu) visar tillsats eller ingen tillsats**, till exempel "Går · inne 21,6 °C · ingen tillsats" eller "tillsats 1 34 %". Samma ruta finns på webben, i appen och i Home Assistant-kortet.

## 1.2.172 (2026-11-23)
- **Tillsatsen (elpatronen) syns i realtid.** Thermia Diplomat via Husdata visar tillsats steg 1 och steg 2 samt hur mycket tillsatsen går (register 26, 27 och 31). Motorn läste redan värdena men sparade dem inte. Nu loggas de, och fliken Värmepump har en färgremsa för senaste 24 timmarna: vilar, värme, varmvatten, tillsats 1 och tillsats 2 (röd).
- **Notisen om tillsats kommer nu när den slår på**, inte först när pumpens timräknare stiger. En notis per tillsatsperiod, ny först när tillsatsen varit av i tio minuter. Pumpar utan de registren använder som förut räknarna.

## 1.2.171 (2026-11-23)
- **Notis när värmepumpen kör på tillsats (elpatron).** Pumpen har egna räknare för tillsatsdrift. Stiger någon av dem skickas en notis med gradminuter och elpris (kategorin Värmepump, kan stängas av under Notiser). Räknaren tickar i hela enheter, så notisen kommer när räknaren stiger och inte i samma sekund tillsatsen kopplas in.

## 1.2.170 (2026-11-23)
- **Tillsatsvakt i rumsåterkopplingen.** När elen är dyr och värmepumpen redan ligger på −700 gradminuter eller lägre (pumpen kopplar in elpatronen nära −1200) höjer EnergyWizard inte längre börvärdet över golvet. Höjningen kräver mer än kompressorn orkar och bara tillsatsvärmen kan leverera, och den kostade en Thermia-ägare ca 150 kr på nio dygn. Gränsen kan ändras med inställningen `heat_aux_guard_dm` (standard −700). Under golvet gäller den hårda stoppen som förut.

## 1.2.169 (2026-11-23)
- **Systemtestets laddboxtest använder 8 A i stället för 6 A.** Mot en riktig Easee med en Tesla startade bilen på ungefär tio sekunder med 8 A (och 16 A), men inte alls med 6 A, trots att kommandona gick fram. Testet kan då inte skilja ett startproblem från ett fel i boxen.

## 1.2.168 (2026-11-23)
- **Systemtestets laddboxtest väntar fyra minuter i stället för 90 sekunder** på att strömmen ska synas. Easee styrs via molnet, och strömmen syntes vid ett skarpt test först efter ett par minuter. Förklaringen när ingen ström kommer visar nu också laddboxens status och väntetiden.

## 1.2.167 (2026-11-23)
- **Systemtestets laddboxtest slår på laddboxen som motorn gör.** En Easee som står på `awaiting_start` fick förut bara en strömgräns och började aldrig ladda, så testet hade felaktigt rapporterat att ingen ström kom. Nu får den ett på-kommando precis som motorn ger.
- **Systemtestet hittar varmvattentemperaturen även för Thermia** (värdet heter `water_temp_top` där). Förut varnade det felaktigt att varmvattnet saknades, fast det syns i grafen.

## 1.2.166 (2026-11-23)
- **Systemtestet ändrar Thermia-pumpens börvärde 1 °C i stället för 0,5 °C.** Pumpen sparar bara hela grader, så 15,5 läses tillbaka som 15 och testet såg aldrig sin ändring (hittat vid ett skarpt test: skrivningen gick igenom men värdet ändrades inte). Drivrutiner kan ange sitt eget steg (`room_target_step`).

## 1.2.165 (2026-11-23)
- **Systemtestet pausar motorns egen skrivning till värmepump, spabad och laddboxar medan det provar dem** (som det redan gjorde för batteriet). Förut skrev motorn tillbaka sitt eget värde inom en minut, så testet av värmepumpens börvärde kunde aldrig se sin ändring. Hittat vid ett skarpt test på en Thermia via Husdata. Börvärdet läses nu som ett enda register (`pump.read_room_setpoint`) i stället för hela registerkartan, eftersom H66-gatewayen bara tål en klient åt gången.

## 1.2.164 (2026-11-23)
- **Testa ditt system kan nu prova styrningen av Thermia-värmepumpar (Husdata).** Rumsbörvärdet läses ur pumpens register (`room_temp_setpoint`), så testet kan ändra det 0,5 °C, läsa tillbaka och sätta tillbaka det. Förut hoppades testet över eftersom drivrutinen inte kunde läsa tillbaka börvärdet. Spabadstestet är körd på en riktig Gecko (Spabad: 38,5 till 39 och tillbaka, bekräftat).

## 1.2.163 (2026-11-23)
- Testa ditt system: luft mellan etikett och värde i resultatlistan, och texten om att något "satts tillbaka" visas bara när ett styrtest faktiskt ändrat något. Sammanfattningen säger inte längre "läsningar" två gånger.

## 1.2.162 (2026-11-23)
- **Testa ditt system: färre falsklarm i läsningarna.** Skyddssensorer (på/av) flaggades som "inte ett tal", och sensorer som står still med rätta (bil som sover, laddbox som inte laddar, målvärden, inställningar) flaggades som gamla. Nu varnas för gammal data först efter 12 timmar och aldrig för börvärden, inställningar eller 0 W, och okända värden på sådant som bara har värde under körning räknas inte som problem.

## 1.2.161 (2026-11-23)
- **Testa ditt system testar nu allt du valt, inte bara batteriet.** Del A läser av alla valda entiteter och drivrutiner (värmepump, spabad, solceller, batteri, elmätare, bilar, laddboxar, maskiner, väder) och säger vad som saknas, inte svarar, är text där tal väntas, orimligt eller gammalt, utan att skicka något. Det fångar bland annat en laddbox utan effektsensor (0 kr i kostnadskortet) och valda givare som aldrig används. Del B är valfria styrtester du kryssar i: batteri (håll, ladda, ladda ur), värmepump (rumsbörvärdet ändras 0,5 °C), spabad (målvärdet ändras 0,5 °C) och laddbox (6 A i högst 90 s, bara om bilen är inkopplad och inte laddar). Varje test läser tillbaka och sätter alltid tillbaka det som ändrats, även efter en omstart mitt i. Värmepumpen provas bara om börvärdet går att läsa tillbaka. Se `docs/system-test.md`. **Styrtesterna är inte provade mot riktig hårdvara**, bara med tester.

## 1.2.160 (2026-11-23)
- **Varmvattenraden i Översikten säger det verkliga läget (#583).** Den stod "14 dagar passerade – Tvingande körning till 60°C" varje varv, med gränsen i stället för det verkliga antalet dagar, och även i skuggläge där inget skickas. Nu står antal dagar sedan varmvattnet senast mättes på legionellatemperaturen (eller att det aldrig mätts), och i skuggläge att ingen tvingande körning skickas.
- **Inställningarna kraschar inte efter en uppgradering (#585).** När en ny version lägger till en kolumn i inställningstabellen kunde motorns långlivade databasanslutningar fortsätta felas med "cached plan must not change result type" tills motorn startades om. Anslutningspoolerna förbereder nu aldrig frågor på servern.

## 1.2.159 (2026-11-22)
- **Färre falska "batteriet följer inte"-notiser.** Säger batteriets drivrutin att batteriet just nu inte kan ge eller ta emot effekt (FTW-drivrutinernas `available_charge_W` / `available_discharge_W`, t.ex. kall cell eller BMS-tak) och batteriet står still, räknas det som begränsat av batteriet och ingen varning skickas. Fel riktning varnar som förut, och står batteriet still fast drivrutinen säger att det kan ge effekt varnar det också som förut. Ändrar bara varningen, aldrig styrningen. Idén kommer från FTW 0.167.0-beta.1.

## 1.2.158 (2026-11-22)
- **Står motorn still får du veta var.** En vakttråd ser efter motorns livstecken var 30:e sekund. Har huvudloopen inte gett livstecken på 15 minuter (och ingen uppgift är med flit upptagen, som veckans backtest) skriver den **en gång** i loggen och skickar som felfall **var huvudtråden står** (fil, rad och funktion, aldrig värden eller sökvägar) tillsammans med anropskedjan, och skriver när det löst sig. Så går det att se vad som hänger sig, till exempel ett nätverksanrop utan tidsgräns, i stället för att gissa. Vakten **startar inte om** något: en omstart kan ge loopar om orsaken är Home Assistant eller databasen, och först när vi sett hur ofta det händer på riktigt går det att avgöra om och hur en omstart ska ske. Containerns hälsa (`unhealthy` efter 10 minuter, 1.2.149) är oförändrad.

## 1.2.157 (2026-11-22)
- **Testa ditt system**: en knapp som kontrollerar att batteriet gör som EnergyWizard ber om (håll, ladda, ladda ur, högst 1 kW, högst två minuter per steg) och sedan sätter tillbaka allt. Den erbjuds som **sista steget i installationsguiden**, efter att installationen och alla val sparats, och finns kvar under *System*. Kräver att batteriet står på `styr`, skickar riktiga kommandon även i skuggläge (bara från testet) efter en bekräftelse, och återställer batteriet även efter en omstart mitt i. Resultatet kan skickas till utvecklaren med en referens, så att vi får veta om en förinställning inte fungerar på riktig hårdvara. Se `docs/system-test.md`. **Ej provat mot ett riktigt batteri**, bara med tester.

## 1.2.156 (2026-11-22)
- **Automatiskt laddschema skriver inte längre över din laddnivå med 100 % (#576).** När en bil kopplas in utan något aktivt framtida schema skapas ett nytt för nästa avfärd. Det fick alltid 100 % och skrev över dagens sparade rad, så den som satt 50 % fick tillbaka 100 % varje gång. Nu behålls din nivå: dagens sparade nivå om den är lägre än 100, annars den vanligaste lägre nivån bland bilens övriga dagar, annars 100.
- **`generic_climate` läser nu ute-, framlednings-, retur- och varmvattengivare samt effekt (`power_w`) om de står under `heat_pump.entities` (#577).** Förut lästes bara climate-entiteten och resten ignorerades tyst. Effekt i W eller kW summeras.

## 1.2.155 (2026-11-22)
- **EnergyWizard lär sig när ni badar och föreslår badtider.** Varje bad registreras (spabadets "i bruk"-sensor `spa.entities.in_use`, eller ett snabbt temperaturfall, samma tolkning som notisen om öppet lock). Under *Badtider* i appen står ett förslag ("Ni har badat 4 gånger sedan 1 nov. Förslag: söndagar 17:00–22:30 …") med knappen *Använd förslaget*, som bara fyller i formuläret: inget ändras förrän du trycker Spara. Det behövs minst 3 bad, annars står det rakt ut att underlaget är för litet. Webbens API har samma förslag (`spa.bath_suggestion`).
- Upptäckten hittar "i bruk"-sensorn för Gecko.

## 1.2.154 (2026-11-22)
- **Notis när spabadet rapporterar ett nytt fel** (Gecko: felkodssensorn, `spa.entities.error`, hittas nu av upptäckten). Första avläsningen sparas utan notis, och sedan meddelas bara när felet ändras till ett annat. Ett fel som står kvar i dagar (Geckos "OverTemp" nollställs inte av sig själv) larmar alltså inte om och om igen. Otillgänglig sensor räknas inte som ändring. Kategori: Spabad.

## 1.2.153 (2026-11-22)
- **Gecko-badets övriga entiteter hittas även om någon döpt om dem (#570).** Upptäckten letade syskon bara via namnstammen (`climate.<bad>_heater` → `sensor.<bad>_current_temperature`). Har du döpt om en entitet, så att climate heter `climate.spabad_heater` men sensorerna `sensor.spa_xxx_current_temperature`, hittades de inte. Nu räknas allt i samma Home Assistant-enhet som badets climate-entitet som syskon, och namnstammen används som komplement. Det du valt själv ändras fortfarande aldrig.

## 1.2.152 (2026-11-22)
- **Versionsnumret syns under System** i webben (stort överst på uppdateringskortet): tilläggets version eller Docker-bildens nummer.

## 1.2.151 (2026-11-22)
- **Gecko-spabadet visar temperatur och går att styra, även om det upptäcktes automatiskt (#570).** Upptäckten kopplade bara badets climate-entitet som "temperatur" (dess tillstånd är text som "heat", inte en siffra) och hittade aldrig badets temperatursensorer, `water_heater` eller ekonomiläge. Då fick motorn ingen temperatur, räknade badet som offline varje minut och kunde inte sätta måltemperatur eller ekonomiläge. Nu hittar upptäckten hela badet via dess namnstam (till exempel `climate.<bad>_heater`, `sensor.<bad>_current_temperature`, `sensor.<bad>_target_temperature`, `water_heater.<bad>_heater` och `switch.<bad>_economy_mode`), och motorn **kompletterar en redan sparad konfiguration på samma sätt**, så ett bad som redan är inlagt börjar fungera utan att du skriver om något. Det du valt själv ändras aldrig. Dessutom läses temperaturen ur climate-entitetens attribut när ingen sensor finns.
- **EnergyWizards egna sensorer väljs aldrig som källa.** Spabadets effektsensor valdes automatiskt som `sensor.smartbox_effekt_spa`, alltså vår egen publicerade utdata, som då matades tillbaka in. Upptäckten hoppar nu över allt som heter `smartbox_*` eller `energywizard_*`, i alla kategorier, och en redan sparad konfiguration släpper dem också. Vill du ange badets effektsensor själv, se avsnittet om spabad i tilläggets dokumentation.
- **Översättning av Sigenergy-noten i guiden** på engelska och tjeckiska (saknades i 1.2.150 och fällde översättningstestet).

## 1.2.150 (2026-11-22)
- **Sigenergy föreslås nu i guiden** (via TypQxQ/Sigenergy-Local-Modbus): Remote EMS-brytaren blir `enable_switch` och "Remote EMS control mode" lägesväljare, med lägena Maximum Self Consumption (auto), Command Charging (Grid First) och Command Discharging (ESS First), bara de som väljaren erbjuder. Det finns inget "håll"-läge. **Ej verifierat mot en riktig Sigenergy:** slå på skuggläget först. Kan Remote EMS inte slås på loggas ❌ och telemetrin rapporterar felet automatiskt (`battery_generic._ensure_enabled`), så att vi får veta om det inte fungerar för någon.

## 1.2.149 (2026-11-22)
- **En motor som hänger sig syns nu.** Huvudloopen skriver ett livstecken varje varv, och motorns container har en `HEALTHCHECK` som blir röd (**unhealthy** i `docker ps` och Portainer) om livstecknet är över tio minuter gammalt. En krasch hanterades redan (omstartspolicyn, `run.sh` i tillägget), men en motor som lever och står still, till exempel ett nätverksanrop utan tidsgräns, upptäcktes inte. Veckans MPC-backtest, som tar lång tid med flit, markerar sig som upptagen så att den inte ger falsklarm. Det här är bara en markering: ingenting startas om av den.
- **COP och värmeeffekt räknas inte längre på en påhittad köldbärartemperatur.** När värmepumpens framledning eller köldbärare saknas (givaren ur) räknades den som 0 °C och gav ett påhittat COP. Nu är COP och värmeeffekt okända tills givaren är tillbaka.
- **Sparat-texten säger vad jämförelsen är.** Måttet jämför sedan 5 november med ett vanligt hushåll utan styrning (en typisk förbrukningsprofil), men webbens ruta sa fortfarande "billigare än dygnets snitt". Webben säger nu "billigare än ett vanligt hushåll", och sparkortet i appen heter "Sparat mot ett vanligt hushåll".
- **Citattecken i fält kan inte längre bryta sidan.** Alla fältvärden i webben och appen går nu genom `esc()` (26 ställen i webben och 4 i appen, mest siffror, klockslag och val från vår egen server). Ett test vaktar att inget nytt oescapat `value="${…}"` smyger sig in. Idén kommer från FTW 0.165.3, som rättade samma sak i sin inställningssida.

## 1.2.148 (2026-11-21)
- **Supportutdraget visar veckan, inte bara de senaste två timmarna** (idé från FTW:s supportfil). Till en felrapport följer nu en rad per dygn de senaste sju: nät köpt och sålt, sol, bil, batteriets lägsta och högsta laddning (dag och natt) och hur ofta batteriplanen byttes, värmepumpens gångtid, hål i minutdatan (omstarter och avbrott) samt antal fel och varningar, plus de vanligaste felen. Bara siffror och sanerade felrader, inga namn eller adresser, och det följer samma val som förut: den som stängt av felsökningsutdrag skickar inget. Det gör det lättare att se om ett fel är nytt eller har pågått länge.
- **Effektavgift: natten kan räknas som en del av effekten.** Vissa nätägare räknar nattens timmar (22–06) som en del, till exempel hälften, när månadens högsta timmar tas ut. Under Elförbrukning → Effektavgift finns nu **Natt (22–06) räknas som … %**. Standard är 100, alltså ingen viktning, så ingenting ändras om du inte väljer det. Med viktning räknas varje nattimmes snitt om innan topplistan tas fram, och gränsen för en pågående nattimme blir högre eftersom bara en del av den räknas. Gränsen räknas också på installationens tid i stället för en fast svensk tid, så den blir rätt även i andra tidszoner och vid sommartidsbytet.

## 1.2.149 (2026-11-22)
- **Batterier där fjärrstyrningen först måste slås på (Sigenergy Remote EMS):** nytt `battery.entities.enable_switch`. EnergyWizard slår på brytaren en gång, väntar tills Home Assistant visar att den står på (högst `enable_wait_s`, standard 30 s, ingen omskrivning) och väljer först då läge. Står den inte på i tid ändras inget läge. Exempel i `battery_generic.py` och `docs/batterier-och-vaxelriktare.md`. Ej provat mot en riktig Sigenergy.
- HA-korten: rad om Marknadsplatsen i HA 2026.11 i `ha-cards/README.md`.

## 1.2.148 (2026-11-22)
- **Färre falska "ReadTimeout" mot Home Assistant (#568).** Skrivningar till number/select (Tesla via Fleet, myUplink) tog ibland över 10 sekunder eftersom integrationen ringer ett moln. Tidsgränsen är nu 20 sekunder, och om båda försöken ändå får timeout läser EnergyWizard entiteten: står den redan på värdet var det ingen tappad styrsignal, och felet rapporteras inte. Går värdet inte igenom är det kvar som ett fel.

## 1.2.147 (2026-11-21)
- **Kontrolljournalen visar vad bilen själv begär** när laddningen ligger under beställningen ("Bilen tar bara 11 A, vi beställde 16 A. Bilen begär 11 A."). Så syns om det är bilen eller laddaren (begär 11 A) eller boxen (begär 16 A) som håller emot. Ange `charging_amps: number.<bil>_charging_amps` under bilens `entities` i husfilen (Tesla via HA:s Tesla-integration).

## 1.2.146 (2026-11-21)
- **NIBE S735 via pumpens lokala REST-API** (`driver: nibe_local`), från pearldrums fork. Frånluftspumpen S735/S735C läses som S1155/S1255 (ute, framledning, retur, varmvatten, rum, kompressorstatus, frekvens, el och uppmätt COP), och varje värde kontrolleras mot pumpens metadata. Utan rumsgivare (vanligt på S735) styrs innetemperaturen via värmekurvans förskjutning: bind `heating_offset` till register 30 (`offset_normal`, `offset_base_c`, `offset_steps_per_c`, `offset_min`/`offset_max`). Färdigt exempel i docs/nibe-local-rest.md. HA-entiteterna får `offset_normal`.
- **Generisk laddare: strömgräns via integrationens tjänst** (till exempel Charge Amps), också från pearldrums fork.

## 1.2.145 (2026-11-20)
- Värmepumpens uppmätta effekt till flödet (`latest_pump_w`) rullar tillbaka transaktionen om tabellen `load_breakdown` saknas, så att en äldre installation inte får följdfel i nästa fråga.

## 1.2.144 (2026-11-20)
- **"Just nu"-grafen i appen växer till kortets hela bredd och använder lediga utrymmet under**: sidans krympsteg var för grova och lämnade tomt bredvid och längst ner på högre skärmar. Grafen får nu växa så länge sidan ryms.
- **Mobilvy i webben**: större avstånd mellan huset och rutorna till höger (linjer och punkter täckte texten), högre rutor.

## 1.2.143 (2026-11-20)
- **Lugnare och luftigare mobilvy**: "Just nu"-grafen har mindre text och mer luft mellan rutorna (ingen text klipps längre), och beslutsrubriken i webbens översikt är mindre på telefon med lite mer avstånd mellan korten.

## 1.2.142 (2026-11-20)
- **Påminnelsen om sponsring säger först vad EnergyWizard sparat dig den senaste veckan** och föreslår en konkret summa (runt 10 USD i månaden). Den visas bara när besparingen är minst 50 och minst tre dygn med data finns; annars väntar den. En andra knapp ("Ge utan GitHub-konto") visas så fort en alternativ betalsida är inlagd.

## 1.2.141 (2026-11-20)
- **Större "Just nu"-graf i mobilappen**: flödet fyller nu kortets hela bredd (smalare rityta, större rutor och text) och använder mer av höjden på Hem.
- **Installationer på mobil**: raderna i husens detaljer flödar inte längre ut över kortets kant, och felgruppens namn bryts på ord i stället för ett tecken per rad (raden får radbrytning, Logg-knappen hamnar under vid smal skärm).

## 1.2.140 (2026-11-20)
- **Rökprov av webbens API i testerna** (`tests/smoke_api.py`): varje GET-väg anropas med inloggning mot en riktig databas, och ett 500 stoppar releasen. Ekonomi-felet (#562) hade fångats här. Provet hittade tre fel till:
  - Obehöriga anrop till Loggutdragen i Installationer (`/api/installs/support`) gav 500 i stället för 403 (`HTTPException` saknades i importen).
  - Elbil-sidan gav 500 på en ny installation tills motorn sparat sin första laddplan: tabellen `ev_plan_slots` skapas nu när motorn startar.
  - Ett webbanrop till Plan kunde hänga för alltid på en ny installation, eftersom det väntade på sitt eget `ALTER TABLE system_settings`: kolumnerna för solprofilen skapas nu vid start.

## 1.2.139 (2026-11-20)
- **Ekonomisidan gav "Internal server error" (#562).** Från 1.2.118 till och med 1.2.137 kraschade `/api/economy` för alla: raden som tar fram dagens datum anropade
  `local_sql.installation_timezone()`, men `local_sql` är en funktion, inte modulen. Rättat, med ett test som bygger hela svaret så att en sådan miss syns. Övriga 56 GET-vägar i webben svarar.

## 1.2.138 (2026-11-20)
- **Webbens Översikt visar också "ladda nu".** Appen fick etiketten i 1.2.134, men webbens flöde skrev fortfarande "laddar" på en bil som laddar på kommandot "Ladda nu". Märkningen kommer nu från servern (en bil med fast ampere
  som faktiskt laddar), så appen och webben visar samma sak.

## 1.2.137 (2026-11-20)
- **Skicka felsökningsinfo (#559).** Under Logg i webben och appen finns en knapp som skickar den sanerade loggen (2 dygn) till utvecklarna och ger en referens, t.ex. `EW-7K3F2`, att skriva i
  ärendet. Loggen läggs aldrig publikt: den saneras i huset och igen i samlaren, sparas i 7 dagar och kan bara läsas av administratörerna med deras nyckel (`/admin/logs?ref=EW-…`, med granskningslogg).
  Felmallen har ett nytt fält *Felsökningsreferens*. Det är samtycke genom att man trycker på knappen; fullständig logg på begäran (med inställningen Kräv mitt godkännande) är inte byggd än.

## 1.2.136 (2026-11-20)
- **Knappar i Bil-kortet i Home Assistant (#557): Auto, Ladda nu, Pausa.** Med MQTT påslaget (Inställningar → Home Assistant via MQTT) får varje bil en väljare, `select.energywizard_ev_<bil>_mode`,
  och kortet visar den som knappar. De sätter samma överstyrningar som appens knappar. Ladda nu laddar tills bilen är full eller kabeln dras ur, och Auto ger tillbaka AI-schemat. Utan MQTT finns
  inga knappar och kortet läser bara som förut. `controls: false` döljer knapparna.

## 1.2.135 (2026-11-20)
- **Webben på telefon:** genomgång av alla 14 sidor på 390 px. Fält med flera värden på samma rad (`Billigt … Dyrt … Spara`, `Börvärde lägst … högst`) klipptes i högerkanten och bryts nu till ny rad.
  Flödesbilden "Just nu" på Översikten blev så liten att texten inte gick att läsa; den använder nu det kompakta läget på smala skärmar (som mobilappen).

## 1.2.134 (2026-11-20)
- **Appens "Just nu" visar "ladda nu" när du själv startat laddningen.** En bil som laddade på kommandot "Ladda nu" visade bara "laddar", medan sidhuvudet sa "Dyrt just nu" och planen ville pausa. Det såg ut som att
  systemet laddade dyrt av misstag. Nu står det "ladda nu" på bilens ruta så länge laddningen är manuell.

## 1.2.133 (2026-11-20)
- **Appens Hem-flik: inget stort tomrum längst ner vid stor text.** När texten är stor eller skärmen liten döljer appen detaljer steg för steg tills allt får plats. Sista steget dolde hela rutan "vad görs nu", som sedan
  rumsåterkopplingen har långa beslutstexter och blivit hög, och det lämnade 150-270 px tomt under knapparna. Nu krymper rutan till en beslutsrad på högst två rader i stället för att försvinna. Mätt i en emulerad
  telefon mot den riktiga appen: tomrummet vid 115 % text gick från 274 px till 126 px (och planrutan syns).
## 1.2.132 (2026-11-20)
- **HeishaMon: samma drivrutin som upstream (0.8.1) plus `control: false`.** Upstream (srcfl/device-drivers#235) rättade samma fel som vi (vakthunden nollställde kurvförskjutningen) två dygn före oss. Vi har bytt
  vår egen rättning mot deras fil och behåller bara ett tillägg: `control: false` gör drivrutinen helt läsande (#491). `NOTICE.md` är rättad.

## 1.2.131 (2026-11-20)
- **Husdata/Thermia: värmepumpens elförbrukning från H66 när du angett watt (#466).** H66 räknar själv ut en summa av de watt du anger per statusvariabel (Compressor, Add heat step 1/2, pumparna) och visar den som
  "Power consumption". Är den större än 0 använder motorn den som pumpens elförbrukning i lastnedbrytningen och COP, i stället för uppskattningen ur framledningstemperaturen. Utan inställda watt är allt som förut.
  Så här ställer du in dem: öppna H66:ans startsida, klicka på t.ex. `0W` vid **Compressor** och skriv ett watt-tal (ange minst kompressorn; tillsatsvärmen får du bara med om den också har ett värde).
  H66 räknar om ungefär en gång per minut. Mätt mot en riktig H66: 60 W på en radiatorpump som gick gav "Power consumption" 60 efter en minut.

## 1.2.130 (2026-11-20)
- **Husdata/Thermia: lärdomar av Husdatas eget Modbus-bibliotek (#466), alla mätta mot en riktig H66.**
  - **Saknad givare är inte längre en temperatur.** En ej inkopplad givare ger ett fast skenvärde (−40,0 °C på en Thermia Diplomat, −48,3 °C på Rego 600). Det läses nu som "saknas", så loggar och styrning räknar inte med det. Det
    hade bland annat kunnat se ut som en frusen köldbärare för nödspärren vid −7 °C. Utetemperaturen får fortfarande vara −40,0.
  - **En Modbus-klient åt gången.** H66 svarar bara en klient i taget; en andra får anslutning men aldrig något svar. Trådarna i motorn pratar nu med pumpen en i taget, och ett nätverksfel (t.ex. när Home Assistant läser
    samtidigt) ger ett enda nytt försök. Mätt mot en riktig H66: två samtidiga läsare lyckades 5 av 10 gånger förut, 10 av 10 nu.
  - **Registerkartan kontrolleras mot gatewayen.** Efter första läsningen läser motorn H66:ans startsida och jämför styrenhet och registerlista med det den förutsätter. Har du en annan styrenhet än Thermia Diplomat
    (t.ex. IVT/Bosch Rego 600, som har en annan karta) står det i loggen att värdena kan vara fel, i stället för att de tyst blir fel.
  - **Skrivvärden kontrolleras innan de når pumpen.** Gränserna läses ur pumpens egna "Setting between"-intervall på startsidan (reservtabell när sidan inte går att läsa). Ett orimligt värde nekas med en tydlig logg och
    pumpen rörs inte.

## 1.2.129 (2026-11-20)
- **"Ladda nu" laddar tills bilen är full eller kabeln dras ur, även "Tills jag stoppar".** Utan mål låg tvånget kvar när kabeln drogs ur och slog till igen nästa gång bilen kopplades in,
  vid vilket pris som helst. Nu avslutas Ladda nu när bilen slutat ladda själv (full eller vid sin egen gräns) eller kabeln dras ur, och planen tar över. Med mål (X %) gäller dessutom målet och 24 timmar.
  Urdragen kabel räknas först några minuter efter att motorn startat, så en omstart rensar inte en pågående Ladda nu.

## 1.2.128 (2026-11-20)
- **Värmepumpens effekt i appens och webbens "Just nu" är elförbrukningen.** Flödet visade kompressorns värmeeffekt (11,5 kW) i stället för det pumpen drar ur nätet (2,7 kW), så värmepumpen
  såg ungefär fyra gånger för stor ut och det syntes inte vad som drog resten av huset. Nu går den uppmätta elförbrukningen före när den är färsk; utan mätvärde är det som förut.

## 1.2.127 (2026-11-20)
- **Korten visar värmepumpens elförbrukning, inte kompressorns värmeeffekt.** Flödet läste `compressor_power_kw`, som för en värmepump är flera gånger elförbrukningen
  (11,5 kW värme mot 2,7 kW el vid COP 4,8). Kortsensorn tar nu den uppmätta elförbrukningen (`load_breakdown.pump_w`) när den är färsk. Appens och webbens flöde rättades i 1.2.128.

## 1.2.126 (2026-11-20)
- **Fler kort för Home Assistant:** `energywizard-heat-card` (termostatratt med inomhustemperatur och band mellan golv och tak, varmvatten, billiga och dyra pass) och
  `energywizard-car-card` (laddnivå, status och planerade laddpass över elpriset, per bil). Kortsensorn har fått värmedata och bilarnas laddnivå och pass.
- **Korten installeras via HACS** (Anpassade arkiv → `https://github.com/murre87/energywizard`, kategori Dashboard). HACS hämtar `dist/energywizard-cards.js` via `hacs.json`.

## 1.2.125 (2026-11-20)
- **Kort för Home Assistant (förhandsversion).** Motorn publicerar nu `sensor.energywizard_kort` (flöde, pris och plan) varje minut, och mappen `ha-cards/` har ett första kort,
  `energywizard-house-card`, som ritar det i appens stil: energiflöde, planklocka eller skyline, och bilar. Samma kort fungerar för tillägget och Docker.
  Se `ha-cards/README.md`.

## 1.2.124 (2026-11-20)
- **Ekonomi: snittpris på såld el (#549).** Rutan Såld el visar nu även vad man i snitt fick betalat per såld kWh, som Köpt el gör. Förslag och kod av larsfrisk.

## 1.2.123 (2026-11-20)
- **Prisstyrning av elvärme per zon (#431, #528).** Element, golvvärme och Adax med egen termostat kan listas som `zones` under
  `electric_heat`: dyrt sätter lägsta börvärde, billigt och kraftigt solöverskott sätter högsta, ett schema går före priset och bortaläge sätter
  lägsta. `control: false` (standard) skriver inget utan loggar börvärdet som skuggåtgärd; sätt `control: true` när det ser rätt ut.
  Startguiden har en lista att kryssa i. Den avstängda `heaters`-listan med beslutsrader från 1.2.119 finns kvar, men guiden skriver
  nu zonblocket.

## 1.2.122 (2026-11-20)
- **Dyr el höjer inte börvärdet när rummen redan är över golvet (#517).** Rumsåterkopplingens prognos
  kunde beställa 23 °C medan de kallaste rummen låg på 21 °C och sparläget var 20,5 °C. Pumpen värmde
  och huset köpte el, trots att översikten sa sparläge. Ligger rummen över golvet stannar börvärdet på
  sparläget eller lägre. När rummen närmar sig golvet höjs det som förut.

- **Elvärmens effekt förklaras (#431).** När `electric_heat` är på kan varje element ha `power_w`, en sensor eller en lista.
  Den uppmätta effekten syns i beslutet och räknas i lastnedbrytningen, så elementet inte blir oförklarad last.
  En givare som redan ligger under `loads` räknas bara en gång. Ingenting skrivs till elementen.

- **Growatt hybrid loggar ett skuggrecept utan att skriva register (#395).** När Home Assistant kan läsa
  batteriet men inte har lägen (ingen Time 1 Mode) kan samarbetsläget tala om vilket registerpar receptet använder:
  självförbrukning är 1102 = 0 och 1092 = 0, håll är 1102 = 1 och 1092 = 0, och full konfigurerad nätladdning är
  1102 = 1 och 1092 = 1. En delad effekt, urladdning och vila tigs, eftersom receptet inte kan uttrycka dem.
  Inga register skrivs, och den engångsinställning receptet kräver görs inte. Styrläge använder inte receptet.
  Growatt som redan har Time 1 Mode styrs som förut.

- **SAJ H2 loggar ett skuggrecept utan att skriva register (#395).** När Home Assistant kan läsa
  batteriet men inte har lägen kan samarbetsläget tala om vilket registerläge receptet använder:
  självförbrukning är 13895 = 2 och 13905 = lägsta nivå, håll är 13895 = 2 och 13905 = högsta nivå,
  och laddning på hela märkeffekten är läge 1 med tidsfönster hela dygnet och 100 %. En delad effekt,
  urladdning och vila tigs, eftersom receptet inte kan uttrycka dem. Inga register skrivs. Styrläge
  använder inte receptet.

- **Närvaro kan stänga av en plugg när det är valt (#217).** `presence_off: true` slår av en påslagen
  plugg när rummet varit tomt, huset borta eller semestern på, efter väntetiden och minsta på-tid.
  Utan flaggan är det fortfarande bara en rad i loggen. Saknat pris och skuggläge skriver inte.
  Pluggen slås inte på igen när någon kommer tillbaka eller elen blir billig.

- **Närvaro slår på en plugg igen när någon är tillbaka (#217).** En plugg som `presence_off`
  stängde av slås på efter minsta av-tid när rummet, huset eller semestern inte längre vill ha den av,
  så länge elpriset inte fortfarande ligger över av-gränsen. Är elen dyrare än så väntar den tills
  priset sjunkit till gränsen, inte tills den billiga återgången. Saknat pris och skuggläge skriver inte.
  En plugg som redan var av slås inte på.

  plugg när rummet varit tomt, huset borta eller semestern på, efter väntetiden och minsta på-tid.
  Utan flaggan är det fortfarande bara en rad i loggen. Saknat pris och skuggläge skriver inte.
  Pluggen slås inte på igen när någon kommer tillbaka eller elen blir billig.

- **Översikten visar börvärdet som beställdes (#517).** Vid dyr el sa beslutsraden "styrs ner till sparläge"
  eller att kompressorlåset höll läget, medan rumsåterkopplingen hade beställt ett annat börvärde (till exempel
  17,5 °C). Beslutet är nu det börvärdet. När låset själv byter börvärde står temperaturen i låsraden.
  Måltemperaturen bredvid innetemperaturen är samma beställda värde, inte bara inställningen för dyr el.

## 1.2.121 (2026-11-20)
- Installationer: det första loggutdraget är uppfällt direkt, så att texten syns (och går att markera och kopiera) utan extra klick.

## 1.2.120 (2026-11-20)
- **Installationer: Logg-knapp per felgrupp** (för den som har en administratörsnyckel till telemetrisamlaren). Visar de sanerade
  loggutdragen direkt i webben. Hämtningen sker med installationens egen nyckel, så samlarens granskningslogg visar vem som tittade.
  De automatiska felärendena på GitHub har ingen loggtext längre, bara en länk till samlarens loggsida (ärendena är publika).

## 1.2.119 (2026-11-20)
- **Elvärme räknas i skugga (#431, #221).** Adax, golvvärme och andra element med egen termostat kan listas under
  `electric_heat`. När värmepumpen är i billigt läge visas elementets tak, och i dyrt läge dess golv, i besluten.
  Ingenting skrivs till elementen. Startguiden lägger listan avstängd i den nedladdade konfigurationen.
- **HeishaMon nollställer inte kurvförskjutningen i onödan (#491).** FTW-drivrutinen skrev 0 °C till
  `Z1_Heat_Request_Temp` vid varje vakthund och omstart, även när Home Assistant styrde förskjutningen.
  Nu skrivs det neutrala värdet bara efter att drivrutinen själv har ändrat förskjutningen. `control: false`
  gör den helt läsande: mätvärdena kommer in, men inget offset kommenderas.

## 1.2.118 (2026-11-20)
- **Ekonomisidans högsta pris går att jämföra med det man betalat (#510).** Snittet under Köpt el räknas
  inklusive moms, nätavgift och skatt, medan Högst idag bara var spotpriset. Snittet kunde därför ligga över
  dagens högsta. Lägst, snitt och högst visar nu vad elen kostar att köpa, och spotpriset står under när det
  skiljer sig. Dygnet är installationens tidszon, samma som för köpt el.
- **Märkesnamn med å, ä, ö, š m.fl. blev fel i telemetrin** ("Škoda" blev "Åkoda"). HA:s svar lästes som latin-1 i stället för
  UTF-8. Rättat, och telemetrisidan visar redan inkomna "Åkoda" som Škoda. Kia, Volvo, Volkswagen, Mercedes och Huawei med
  olika stavningar samlas också under ett märke.
- **Webbsidan:** ny sektion "Utrustning som stöds och som körs" (stöd i tre nivåer och märken ur telemetrin), och "Nytt" visar de
  senaste veckornas funktioner. Listan över märken uppdateras av `scripts/export_public_equipment.py`.
- Telemetrisidan döljer poster som inte är utrustning av kategorin (t.ex. rökvarnare, gräsklippare och surfplattor som valts som elbil i
  startguiden) och visar hur många som dolts.

## 1.2.117 (2026-11-20)
- **Beslutsraden visar det som faktiskt beställdes.** "Prio 5b" (rumsåterkopplingen) kändes inte igen av sammanfattningen,
  så den gamla grundlägesraden "Dyr el, styrs ner till sparläge" visades medan börvärdet i själva verket höjts till
  golv + 1. Skuggläget räknas inte längre som ett beslut.
- **Spabadets plan jämför inte längre med ett påhittat pris.** Tider efter sista kända elpris (morgondagens publiceras
  först vid ca 13) fylldes med det sista priset; de får nu genomsnittet av de kända priserna. Tidstillägget på
  0,05 kr/h före badtiden är borttaget, så valet av uppvärmningstimmar går på pris och sol.
- **Telemetrisidan grupperar utrustning per märke.** Alla NIBE-varianter (NIBE Energy Systems, Nibe, F750, S1256, VVM ...)
  blir en rad med modellerna bakom en klickbar rad, och samma sak gäller Easee, Tesla och övriga märken.

## 1.2.116 (2026-11-16)
- **Startfel vid saknat värmestopp (#449, #464, #470).** Saknade värden för pumpens värmestopp eller
  utetemperaturens femdygnsmedel får inte längre huvudloopen att krascha med ett `NoneType`-fel.
  Databastabellerna för elpriser och lastfördelning skapas också före första styrvarvet, så att
  Home Assistant-publiceringen fungerar även på en ny installation. Befintliga inställningar och historik bevaras.

## 1.2.115 (2026-11-15)
- **ML-styrt varmvatten** (Av / Skugga / På under Varmvatten på webbens värmepumpssida). Startvärdet väljs efter de
  inlärda varmvattenvanorna och elpriset. Pumpen väntar på dyra timmar när ingen tappning väntas (start 30 °C) och
  fyller tanken på de billigaste kvartarna före nästa troliga tappning (start 50 °C). Stoppvärdet (toppvärmningen) rörs
  inte, och legionella, felskydd, minuspris och solöverskott går före. Utredningen i #446 visade att Thermia jämför
  startvärdet med en viktad tanktemperatur, där givaren längre ned väger 65 %, och inte med topptemperaturen.

## 1.2.114 (2026-11-15)
- Badtider: veckodagarna tisdag–fredag visades på svenska i engelsk och tjeckisk vy. Rader som går över midnatt visar
  nu "→ nästa dag", och en förklaring visar att varje rad räknas från sin egen dag (torsdag 22:00–15:00 = torsdag kväll
  till fredag 15:00).

## 1.2.113 (2026-11-15)
- **Rumsåterkopplingen: golvvakten går på de två kallaste rummen.** Snittet av de två kallaste rumsgivarna avgör när
  börvärdet höjs nära golvet, inte medianen. Medianen låg på 21,0 °C när två rum var nere på 20,4–20,7 °C.
- **ML väljer börvärdet.** En modell lärd på husets egen logg (45 dygn) förutsäger hur innetemperaturen ändras med
  börvärde, eftersläpning och utetemperatur. Dyrt: lägsta börvärde som håller de två kallaste rummen 0,2 °C över
  golvet fram till nästa billiga period (högst 8 h fram). Billigt: högsta börvärde som håller huset 0,3 °C under
  maxgränsen. Modellen rättar sin nivå mot hur det faktiskt gick de senaste två timmarna och lärs om varje dygn.
  Inställningen för lägsta och högsta börvärde är kvar som yttre gränser. Med för lite data gäller den tidigare
  regeln.

## 1.2.112 (2026-11-15)
- **Innetemperaturen läste sitt eget värde.** EnergyWizards egen publicerade sensor `sensor.smartbox_inomhustemp`
  föreslogs som rumsgivare (namnet innehåller "inomhus") och kunde väljas. Medianen läste då sitt eget gamla värde och
  fastnade, hos oss på 21,1 °C i tre timmar medan rummen svalnade. EnergyWizards egna entiteter räknas nu aldrig in i
  inne- eller fukttemperaturen och föreslås inte längre i givarvalet.

## 1.2.111 (2026-11-15)
- **Ordning för solöverskott (#430)**, på webbens Solceller-sida (förslag från Emlben, #420): husbatteri, elbil,
  spabad, varmvatten och huset i den ordning man vill. En last längre ned startar bara när ingen last ovanför vill ha
  överskottet och kan starta på det. En last som redan går tar sin del, och det som blir över får nästa. Står en last
  före husbatteriet vilar batteriet medan lasten vill ha överskottet, så att det inte balanserar mot lasten. Utan egen
  ordning gäller det inbyggda beteendet som förut.

## 1.2.110 (2026-11-15)
- **Spabad: tider vi inte badar.** Badtiderna kan nu anges omvänt, som tider då man inte badar, t.ex. 22:00–16:00
  på vardagar (tiden får gå över midnatt). Då får badet svalna, och planeraren värmer det på de billigaste timmarna så
  att det är varmt när tiden tar slut. Hur långt det sjunker räknas fram ur de inlärda modellerna för hur fort badet
  svalnar och värms. Övrig tid hålls badet varmt. Val mellan "Tider vi inte badar" och "Tider vi badar" i webben
  (Spabad) och appen (Badtider).

## 1.2.109 (2026-11-15)
Genomlysning av hela systemet mot en veckas data:
- **Resplan i appen:** knappen "Resplan" på bilkortet har funnits sedan första versionen men anropade en funktion som
  aldrig byggdes, så den gjorde ingenting. Nu öppnar den ett engångsmål: klar idag eller imorgon vid ett klockslag
  med en laddnivå. Laddplanen räknar med det som "klar senast", och veckoschemat ändras inte.
- **Varmvattenvanorna lästes om varje minut** (60 dygns logg, cirka 86 000 rader). Nu en gång per dygn.
- **Prisformen** för prognoser bortom Nord Pools horisont frågade databasen för varje kvart när den saknade data. Ett
  tomt resultat gäller nu en timme.

## 1.2.108 (2026-11-15)
- **Elbil: solladdning per bil (#428)** under "Laddregler" (förslag från Emlben, #420):
  - **Solmål:** solladdningen slutar vid målet, t.ex. 80 %. Tomt = bilens egen laddgräns som förut.
  - **Start vid överskott:** solladdningen startar först när överskottet ut på nätet är så stort, t.ex. 4 kW (lägst
    1,4 kW som förut).
  - **Balanspunkt:** 0 = noll export som förut, plus tillåter lite köp, minus behåller lite export.

## 1.2.107 (2026-11-15)
- **Elbil: mål utan klar-tid (#426)**, per bil under "Laddregler" på webbens Elbil-sida (förslag från Emlben, #420):
  - Ett laddmål i % utan klockslag gäller när laddschemat inte har något påslaget mål. Laddningen läggs på de
    billigaste kvartarna bland alla kända priser, även morgondagens när de har publicerats (runt kl 13). Planen räknas
    om var 15:e minut, så den väntar in morgondagens priser om de är lägre. "Vänta högst" (standard 36 timmar) sätter
    en gräns.
  - **Morgongolvet går att ställa per bil** (standard 50 % kl 06, 0 = av). Med ett mål på 50 % och golvet på 50 %
    laddar bilen alltid före 06, så för att vänta på morgondagens priser behöver golvet sänkas eller stängas av.
    Golvlarmen och notisen om missad laddning följer bilens golv.

## 1.2.106 (2026-11-15)
- **Elbil: bara sol (#427) och maxpris (#429)**, per bil på webbens Elbil-sida under "Laddning från nätet" (förslag från
  Emlben, #420):
  - **Bara sol:** ingen planerad laddning från nätet, inte heller morgongolvet. Solladdning och Ladda nu fungerar som
    vanligt.
  - **Ladda aldrig över X kr/kWh:** planerade kvartar dyrare än så tas bort. Jämförs med spotpriset i prisgrafen.
    Morgongolvet (50 % kl 06) undantas, eftersom det är en säkerhet.
  - Underhållsladdningen inför en förutsedd avresa (AI-vanor) följer också reglerna.

## 1.2.105 (2026-11-15)
- **Sol- och baslastprofilerna tränades om flera gånger i minuten** när det fanns för lite data (ny installation,
  eller nästan inget nätköp), med en fråga över ett års logg varje gång (#434). Ett tomt resultat gäller nu en timme
  innan nästa försök.
- **Startpåminnelsen för nya installationer:** när Home Assistant startar om samtidigt som EnergyWizard (502 eller
  inget svar) görs nu tre nya försök, och det loggas som en varning i stället för ett fel (#434).

## 1.2.104 (2026-11-15)
- **Solis RC-batteri (#443, rättning av Lars Frisk):**
  - Läget "håll" finns nu: tvångsladdning med 0 W. Utan det föll håll tillbaka till auto och husbatteriet laddade ur i
    elbilen.
  - Läget skrivs före effekten. Integrationen solis_modbus skriver om effekten ur sin registercache direkt efter
    lägesvalet, så den nya effekten skrevs över (300 W i stället för 2,8 kW).
  - Håll vid liv körs i 10-sekundersloopen, så tvångsladdning och håll inte släpper efter växelriktarens RC Timeout
    (5 minuter). Gäller bara drivrutiner med keepalive_s, aldrig under säkerhetsregler.

## 1.2.103 (2026-11-15)
- Legionella på webben: raden med intervall, temperatur och Spara bryts nu på smala skärmar (knappen hamnade utanför
  kortet med stor text på mobil), och "dygn" översätts i engelsk och tjeckisk vy.

## 1.2.102 (2026-11-15)
- **Innetemperaturen när rumsgivarna glappar:** saknas alla valda rumsgivare en kort stund behålls deras senaste värde
  i upp till 15 minuter, i stället för att värmepumpens egen innegivare tas. På en Thermia via Husdata är den ett fast
  värde (20,0 °C), så rumsåterkopplingen höjde börvärdet i onödan.
- **Legionella på webben:** under Varmvatten på värmepumpssidan kan intervallet (3-60 dygn) och temperaturen (55-65 °C)
  ställas, och det syns när varmvattnet senast nådde temperaturen.
- **Backtester för värmepumpen** i `scripts/backtest_heat/`: export (kvartsaggregerad, med tidsgräns), gemensam
  husmodell, pausvarianter och rumsåterkopplingens regel som i motorn.
- Namn från Home Assistant och användaren (enheter, radiatorer, områden, hus) översätts inte längre på webben, och
  enhetsnamnen escapas.

## 1.2.101 (2026-11-15)
- **Laddplanen hoppade över billiga kvartar på dagen** (#438). Alla kvartar 07-20 fick ett påslag på 1,50 kr/kWh i planens
  rangordning, även på helger och med effektvakten avstängd. En söndag valdes därför natten för ca 1,00 kr före 13:30
  för 0,90 kr. Påslaget gäller nu bara effekttariffens höglasttid (inställd eller standard) när effektvakten är på.
  Kvartarna jämförs också med tidstariffen inräknad, när en sådan är inställd.
- **Solladdning med okänt fasläge gav nätköp** (#439). Easee-laddboxens fasläge går inte att läsa, och efter en omstart var
  det okänt. Solladdningen räknade då ström för 1 fas medan laddboxen körde 3 faser, och bilen drog tre gånger mer än
  solen gav. Okänt fasläge räknas nu som 3 faser, så att motorn växlar till 1 fas innan den ger 1-fasström.
- **Hemmets position var hårdkodad** (#440) till en ort i Småland för alla installationer. Den styr väderprognosen (moln och
  därmed solprognos) och bilarnas avstånd hem. Positionen hämtas nu från Home Assistants `zone.home`, eller från
  `HOME_LATITUDE`/`HOME_LONGITUDE` om de är satta.
- **GPS-hemkomsten** räknade första avläsningen efter en omstart som "på väg hem", och släppte aldrig flaggan för en bil
  som stod still. Nu krävs ett verkligt närmande, och flaggan släpper efter 10 minuter utan närmande.
- **Kontaktorskyddet** (30 minuters laddning efter start) gäller bara bilar som sitter i laddaren, inte en som är på
  väg hem. Loggraden använder bilens namn.

## 1.2.100 (2026-11-15)
- Kompressorlåsets klockslag i loggen visas nu i husets tid (prisområdets tidszon). I 1.2.99 stod det fortfarande i
  UTC eftersom motorns container kör UTC.

## 1.2.99 (2026-11-15)
- **Rumsåterkopplingen slog inte igenom efter ett lägesbyte.** Kompressorskyddet (Prio 8) låser pumpen i dyrt eller
  billigt läge i 45-60 minuter efter ett byte, och skrev då tillbaka lägets vanliga börvärde över återkopplingens.
  Med återkopplingen på behålls nu dess börvärde när låset gäller samma läge som den räknade för.

## 1.2.98 (2026-11-15)
- **Värmepump via Home Assistant-entiteter: egna effektgivare** (#404). `heat_pump.entities.power_w` kan peka på en
  eller flera effektgivare (t.ex. en för värme och en för varmvatten), som summeras. W och kW känns igen. Då används
  uppmätt eleffekt i lastnedbrytningen och COP i stället för en uppskattning ur framledningen.

## 1.2.97 (2026-11-14)
- **Svenska kvar i engelsk och tjeckisk vy:** genomgång av appen, webben och motorns meddelanden. Cirka 65 texter
  saknade översättning, bland annat "Gråzon", "Laddat", "Veckan", "imorgon", "Alla delar" och "Elpris dygnet".
  Alla finns nu på engelska och tjeckiska.
- Översättningen behåller nu en avslutande parentes som hör till texten ("Gråzon (1,39 kr).") i både appen och
  motorn. Förut föll sådana texter tillbaka till svenska.
- **Nytt test:** varje synlig svensk text i appen och webben måste finnas på engelska och tjeckiska, annars stoppas
  ändringen.

## 1.2.96 (2026-11-14)
- **Rumsåterkopplingen: börvärdets intervall är en inställning** (Värmepump → Måltemperatur, "Börvärde lägst" och
  "högst", 15–25 °C). Tomt ger standard: en grad under dyrt-temperaturen och en grad över billigt-temperaturen.
  Golvvakten och maxgränsen gäller som förut, så innetemperaturen hålls mellan dem.

## 1.2.95 (2026-11-14)
- **Värmepumpen kan följa rumsgivarna** (valfritt, Värmepump → Måltemperatur → "Följ rumsgivarna": Av / Skugga /
  På). För pumpar utan egen innegivare, som Thermia via Husdata, avgör värmekurvan temperaturen. Med börvärdet 20 °C
  blev det cirka 21,6–21,9 °C inne, och kompressorn värmde under dyra timmar fast huset hade värme att ge av. Med
  återkopplingen väljs börvärdet efter hur varmt det faktiskt är: dyrt och varmt hus ger en grad under
  dyrt-temperaturen, nära golvet höjs det alltid, och billigt lagrar värme med en grad över billigt-temperaturen tills
  huset är 0,5 °C under maxgränsen. Över maxgränsen tar det befintliga stoppet över. Backtest mars–november: cirka
  270 kr för ett hus, med golvet hållet (lägst 19,8 °C, kort) och mycket mindre tid över 22 °C. Av som standard.

## 1.2.94 (2026-11-14)
- **Rättat: bilarnas laddnivå visades som "–" i appen sedan 1.2.84**, fast Home Assistant hade värdet. En
  kommentar hamnade mitt på raden som skickar bilens läge till appen, så laddnivå, status, kabel, hemma/borta och
  laddning föll bort. Ett nytt test kontrollerar att alla fälten skickas.

## 1.2.93 (2026-11-14)
- Översättningar: när två textmallar passar väljs nu den mest specifika (mest fast text) i stället för den som
  råkar stå först i katalogen. Det gav t.ex. "objednáno paus" i felsökningsvyn i stället för "objednáno pauza".

## 1.2.92 (2026-11-14)
- **Planens indata får ett kvalitetsbetyg** (#389): varje sparad batteriplan anger hur stor del av priserna som var
  riktiga (inte framfyllda) och från vilken källa, om solprognosen kom från Home Assistant eller den egna
  vädermodellen, om förbrukningen kom från den inlärda profilen, och om batteriets laddnivå var känd. Det rapporteras
  bara och styr ingenting. Äldre sparade planer kan fortfarande spelas upp.
- **Aviseringshistoriken tappar inte rader när databasen är överbelastad** (#387): raden väntar (högst 200, med
  händelsens ursprungliga tid) och sparas vid nästa tillfälle eller inom en minut. Inga dubbletter, och själva
  aviseringen skickas aldrig om.

## 1.2.91 (2026-11-14)
- **Felsökning per kvart på webben** (#386): under "Höll vi planen?" i Historik finns "Per kvart (felsökning)" med
  pris, vad varje enhet beställdes och vad den gjorde, hur många av kvartens minuter som loggades och mättes, och
  uppmätt energi för elbil och batteri. Avvikande kvartar markeras. Bara läsning, och saknade minuter räknas aldrig
  som att planen följdes.

## 1.2.90 (2026-11-14)
- **Besparing jämfört med batteriet i självförbrukningsläge** (#398): för den som har husbatteri visar
  besparingsrutan i appen vad styrningen gav utöver ett batteri i växelriktarens vanliga självförbrukningsläge, t.ex.
  "+12 kr mot självförbrukning". Det räknas på samma uppmätta kvartar, med samma batterigränser och verkningsgrad som
  planeraren. Kräver `battery.capacity_kwh` i installationen.

## 1.2.89 (2026-11-14)
- **Varning innan bilen missar sitt mål** (#390): när bilen inte hinner till målet (schemat, "klar senast" eller
  morgongolvet) ens med full effekt kommer en avisering direkt, och bilkortet visar t.ex. "Hinner inte 100 % till
  07:00: behöver 50 kWh, hinner ladda ungefär 20 kWh med 3,7 kW. Väntat: cirka 66 %." Effekten räknas med
  laddboxens egna gränser (lastbalansering, kretsens märkström). Förut kom bara en varning för morgongolvet kl 04:30
  och en notis i efterhand.
- Notisen om missad laddning tar med laddboxens begränsning när den förklarar varför.

## 1.2.88 (2026-11-14)
- Översatt: hälsningen överst i appen ("God morgon, Emil") och "Data 16 h gammal" på bilkortet stod på svenska i
  tjeckisk vy (och delvis i engelsk).

## 1.2.87 (2026-11-14)
- **"Toppa husbatteriet nu till X %"** (#396): tryck på batteriet i flödet. När EnergyWizard styr batteriet finns
  knapparna 60, 80 och 100 %. Batteriet laddar direkt, alltid inom säkringens utrymme, tills målet nås eller efter
  6 timmar. Sedan tar planen över, med en avisering. Säkerhetsreglerna (gammal data, överlastad säkring,
  effekttak) går före. Utan styrning visar rutan laddnivån och var styrningen slås på.

## 1.2.86 (2026-11-14)
- **Varmvatten "Till" med tid** (#397): appen frågar hur länge (30 min, 1, 2, 4 eller 6 h, eller "Tills jag
  ändrar"), och varmvattnet går tillbaka till Auto av sig själv när tiden gått ut. Rutan visar "Auto om 1 h 20 min".
  Förut gällde "Till" tills man själv valde Auto igen.

## 1.2.85 (2026-11-14)
- **Appen: "Just nu"-raderna försvann och flödet krympte** i den nya stilen. Hemskärmen krymper innehållet steg
  för steg när det inte får plats, men det sista steget togs aldrig bort igen. Hade sidan en gång varit för full
  (till exempel medan data laddades) doldes raderna om vad som görs nu, och flödesdiagrammet blev en liten ruta med
  tomma sidor tills appen laddades om.
- Översatt: "Huvudbil: …" för alla bilnamn (förut bara "Nissan" och "Tesla").

## 1.2.84 (2026-11-14)
- **Appen förklarar när laddboxen ger bilen mindre ström än EnergyWizard bad om** (#385), t.ex. "Laddboxen
  begränsar till 12 A: lastbalansering. EnergyWizard bad om 16 A." Förklaringen bygger bara på laddboxens egna
  värden: erbjuden ström, lastbalanseringens kretsgräns (Easee Equalizer) eller kretsens märkström. Annars står det
  att orsaken är okänd. Styrningen och säkringsgränserna ändras inte. Guiden hittar nu Easees "dynamisk
  kretsbegränsning".

## 1.2.83 (2026-11-13)
- **"Ladda nu till X %"** (#394): "Ladda nu" frågar efter mål (40, 60, 80, 100 % eller "Tills jag stoppar").
  Med ett mål slutar laddningen av sig själv när bilen når målet, när kabeln dras ur eller efter 24 timmar, och
  sedan tar planen över, med en avisering när målet nåtts. Förut laddade bilen tills man själv valde Auto, även på
  dyra timmar. Bilkortet visar "Laddar till 80 %". Säkringsskyddet gäller hela tiden.

## 1.2.82 (2026-11-13)
- **Husbatteriets laddning från nätet håller sig inom säkringen** (#399). Förut laddade batteriet med full effekt
  (vid minuspris och planerad laddning) oavsett vad huset drog, och säkringsskyddet grep in först när säkringen
  redan var överbelastad. Nu får batteriet bara säkringens lediga utrymme. Ryms det inte håller det i stället.
- **Elbilen och husbatteriet får inte samma utrymme samtidigt**: en ökning som just beviljats räknas mot den andra
  lasten tills den syns i mätningen (högst 90 sekunder). Minskningar och strypningar fördröjs aldrig.
- Ny inställning `battery.phases` (1 eller 3, standard 3): växelriktarens faser, för en enfasig räknas taket på den
  värsta fasen.

## 1.2.81 (2026-11-13)
- **Prissensorn väljs automatiskt** där Nord Pool inte täcker landet (t.ex. Australien och Tjeckien) och ingen
  sensor är vald: EnergyWizard letar upp prissensorn i Home Assistant själv. Landets egen källa går före (Amber i
  Australien, OTE i Tjeckien), och momsen följer integrationens vanliga format om man inte angett något. Webben
  visar att sensorn är vald automatiskt, och man kan välja en annan.

## 1.2.80 (2026-11-13)
- **Webben, Elpris: rättade texter.** "Publicerade priser" och "Sensor för aktuellt pris" stod på engelska i
  svensk vy, och exempelraden ("spotpris 1,00 € exkl. moms blir …") stod delvis på svenska i tjeckisk vy.
- Inställningarna som bara gäller en prissensor i Home Assistant (moms i sensorn, publicerade priser, sensor för
  aktuellt pris) visas bara när en sensor är vald.
- En vald prissensor som inte längre finns i Home Assistant visas som vald med "hittas inte i Home Assistant", i
  stället för att väljaren tyst visar standardkällan.

## 1.2.79 (2026-11-13)
- **Elpriset utanför Sverige hämtas direkt från Nord Pool** (#392): Norden, Baltikum, Nederländerna, Belgien,
  Frankrike, Tyskland, Österrike, Polen och Storbritannien, i rätt valuta och utan nyckel eller prissensor i Home
  Assistant. Har man valt en prissensor (t.ex. elleverantörens pris) används den som förut, och Nord Pool tar över
  när den slutar fungera. Det var orsaken till de flesta prisfelen utanför Sverige (#210, #211). Tjeckien och
  Australien använder prissensorn i Home Assistant som förut.
- **Guiden föreslår inte längre fel enheter som elbil eller husbatteri** (#393): mobiltelefoner, surfplattor,
  robotgräsklippare, UPS, brandvarnare och andra sensorer valdes ibland, eftersom korta bilmärken som "mini" och
  "smart" matchade mitt i modellnamn och en positionsspårare räckte för att räknas som bil.

## 1.2.78 (2026-11-13)
- **myUplink: inloggningen håller** (#384). myUplink byter refresh-token vid varje förnyelse, men EnergyWizard
  fortsatte använda den gamla, så efter en tid nekades varje inloggning (400 Bad Request) och värmepumpen styrdes
  inte. Nu används den nya direkt och sparas i datamappen. En egen ny `MYUPLINK_REFRESH_TOKEN` går alltid före.
  Nekas inloggningen ändå kommer en tydlig varning och en avisering om att logga in igen, nya försök görs var
  30:e minut, och det räknas inte längre som programfel.
- Översatt: brödtexten i aviseringen om onormal baslast ("Huset drar 4,5 kW") (#202).

## 1.2.77 (2026-11-13)
- **Thermia: varmvattnets startvärde hålls inom pumpens intervall** (30–55 °C enligt installatörsmenyn
  SERVICE → HOT WATER). Bortaläge och effekttak bad om start 5 °C, vilket pumpen inte tar emot.
- **Kontrollen av start/stopp görs nästa kvart** i stället för direkt efter skrivningen. Husdata-gatewayen visar
  ett nyskrivet värde först efter ungefär en halv minut, så den direkta kontrollen kunde varna i onödan.
- Thermias stoppregister är nu belagt i manualen som legionellakörningens stopptemperatur (TOPH. STOP, 60 °C från
  fabrik, 50–65 °C). EnergyWizard rör det inte (sedan 1.2.76).

## 1.2.76 (2026-11-13)
- **Thermia via Husdata: bara varmvattnets startvärde styrs.** Kompressorns varmvattenladdning stoppar vid
  pressostaten, inte vid stoppregistret (Thermias manual). Stoppregistret styr troligen elpatronens toppvärmning,
  så det lämnas nu som installatören satt det. Det enda som avgör när en ren varmvattenladdning startar är
  startvärdet, och det sänks som förut när elen är dyr.
- **Övriga pumpar som före 1.2.74**: för HeishaMon, ThermIQ, NIBE och myUplink är stoppvärdet laddningens mål
  (för HeishaMon den enda spärren), så dyrt ger åter stopp 40 °C och start 35 °C. 1.2.74 höll stoppet på
  normalnivån för alla pumpar, vilket tog bort spärren för HeishaMon.
- Thermias växelventil (varmvatten eller husvärme) loggas varje minut, så att varmvattenladdningar kan mätas
  exakt.

## 1.2.75 (2026-11-13)
- **Ruta om det nya utseendet**: den som uppdaterat och får den nya stilen ser en gång en ruta i appen som
  berättar vad som ändrats och hur man byter tillbaka (Inställningar → Appen → Stil → Klassisk), med knapparna
  "Behåll det nya" och "Byt till klassisk". Nya användare och den som redan valt stil ser den inte. På svenska,
  engelska och tjeckiska.
- Varmvattnets tillbakaläsning (1.2.74) läser start och stopp i en läsning och försöker en gång till om
  Husdata-gatewayen släpper anslutningen.

## 1.2.74 (2026-11-13)
- **Varmvattenspärren vid dyrt elpris fäster nu** (Thermia via Husdata): när elen är dyr sänks bara
  varmvattnets startvärde (så ingen dyr laddning startar förrän tanken är kall). Stoppvärdet ligger kvar på
  normalnivån. Förut sänktes även stoppet till 40 °C, vilket pumpen inte tog emot (den visade 60 °C), så en
  laddning som ändå startade under en dyr timme gick ända upp till 60 °C.
- Efter varje ändring läses start- och stoppvärdet tillbaka från pumpen. Fäster de inte görs nya försök (högst
  tre per värde) med en varning i loggen, i stället för att motorn tyst tror att det gick.

## 1.2.73 (2026-11-13)
- **Ny stil i appen (standard)**: lugnare ytor utan gradienter, glas och färgad glöd, en accentfärg bara på det som
  betyder något, inga emoji i flödet och planen, inga versaler med spärrning, lättare vikter och en enda knappstil.
  Överst står priset just nu ("Billigt just nu · 0,83 kr/kWh") i stället för en slumpad rad. Flödet "Just nu",
  laddringen och skylinen behåller sina färger.
- **Klassisk stil** finns kvar under Inställningar → Appen → Stil, för den som vill ha det gamla utseendet (med
  glas och dygnsfärger som förut). I den nya stilen är glas och dygnsfärger av som standard men går att slå på.

## 1.2.72 (2026-11-13)
- **Större graf i appens Historik** (#371): tryck på effektgrafen så öppnas en stor, lättläst version med axlar,
  tider och teckenförklaring, samma periodval (24 h, 7 d, 30 d, 1 år) och värdena där man trycker eller drar med
  fingret.
- Översatt: "30 dagar" och raden under varje enhet i "Höll vi planen?".

## 1.2.71 (2026-11-13)
- **Laddplanen räknar med kyla** (av natanoj, valfritt och avstängt som standard): när det blir kallare drar värmen
  mer, så säkringen räcker till mindre ström åt bilen och laddningen sprids över fler timmar. Hur mycket mer huset
  drar per grad lärs ur historiken (eller anges). Slås på med `ev_planning.heating_adjustment.enabled: true`, se
  `config/house_config.example.yaml`. I projektets hus lär den sig ungefär 0,13-0,16 kW per grad under 10 °C.

## 1.2.70 (2026-11-13)
- **Säger till när en nyare version finns**: appens sidhuvud visar "✓ senaste" bara när det är bekräftat, annars en
  knapp "Ny version X" med hur man uppdaterar. Webben visar en banderoll överst på Översikt, och motorn skickar en
  avisering per ny version. HA-tillägget frågar Supervisor (nytt: `hassio_api: true`), Docker jämför med senaste
  bildbygget. Fel som redan är rättade försvinner först när man uppdaterat; de flesta hus körde en äldre version.

## 1.2.69 (2026-11-13)
- **"Databasen svarar inte" blir ett samlat fel** när disken inte är full: `PoolTimeout` och liknande rapporteras som
  ett enda fel (`database: DatabaseUnavailable`) i stället för ett per modul, så att en riktig bugg (som poolfelet i
  PR #363) inte försvinner ur sikte. Full disk rapporteras fortfarande inte; användaren får en avisering som förut.

## 1.2.68 (2026-11-13)
- **Kompressorn via myUplink** (#184): den direkta myUplink-drivrutinen tolkar NIBE:s kompressorstatus (koderna
  20/40/60/100 och text som "Kör") som HA-vägen. Förut räknades varje kod över 0, även "stoppad", som att pumpen gick.
- **Appens aviseringar på installationens språk** (#202): "fulladdad", "kabeln lossnade", "lampa offline" och
  "sensor saknas" översätts nu som motorns aviseringar.

## 1.2.67 (2026-11-13)
- **Full disk och databasen nere räknas inte längre som fel i EnergyWizard**: de beror på datorn den körs på. De
  rapporteras inte, syns inte som fel på Installationer och blir inga ärenden, och husets logg visar dem som
  varningar. I stället får användaren en avisering (högst var sjätte timme): "Disken är full" eller "Databasen svarar
  inte", med vad man kan göra.

## 1.2.66 (2026-11-13)
- **Felrapporterna får loggen med** (#227): när ett fel rapporteras följer husets logg de senaste två timmarna med
  (högst 400 rader), utöver felraderna och de senaste besluten, så att felet går att förstå utan att fråga.
- **Inget känsligt följer med**: allt saneras rad för rad i huset (`log_scrub.py`) och igen i samlaren innan det kan
  hamna i ett offentligt ärende. Bort tas husets egna namn ur Home Assistant och inställningarna (platsen, personer,
  zoner, telefoner, användare, bilnamn som blir `<bil 1>`, `<bil 2>`), adresser och värdnamn, IP- och MAC-adresser,
  e-post, token och nycklar, lösenord, koordinater och serienummer. Entiteter visas bara med sin domän
  (`sensor.<…>`). En rad där något ändå ser känsligt ut tas bort helt. Felsökningsutdraget går som förut att stänga
  av i Inställningar.

## 1.2.65 (2026-11-10)
- **Licenser och ursprung förtydligade** (#231): FTW-drivrutinerna från srcfl/device-drivers används enligt deras
  licens (AGPL-3.0). Upstreams LICENSE, NOTICE, LICENSING och tredjepartsnotiser följer nu med, och ändringen i
  `deye-svk.lua` (#215) står i `smartbox/ftw_drivers/NOTICE.md`. Påståendet att Sourceful gett ett särskilt OK är
  struket. Licenstexten följer med i alla bilder.
- **Telemetrin**: fortfarande alltid på i EnergyWizards byggen och utan avstängning, men den beskrivs inte längre
  som ett villkor för att använda programmet. AGPL ger alla rätt att ändra koden, även ta bort telemetrin.

## 1.2.64 (2026-11-08)
- **Språket följer Home Assistant**: har installationen inget eget valt språk används Home Assistants språk, i appen,
  på webben och i tilläggets logg. Valt språk i EnergyWizard går som förut före. (Idé från Energy Pilot.)
- **Tilläggets logg på installationens språk**: motorns utskrifter och startmeddelandena översätts med samma ordlista
  som gränssnitten. De vanligaste raderna (planer, beslut, laddning, spabad, modeller) är översatta till engelska.
  Husets egen logg (Inställningar → Logg) sparas som förut och översätts när den visas.

## 1.2.63 (2026-11-08)
- **Engelska överallt** (#202): drygt 250 texter som fortfarande var på svenska är översatta (Inställningar,
  Elbil, Historik, Aviseringar, Installationer). Översättaren hittade inte texter som stod med emoji eller
  skiljetecken först i ordlistan; de matchar nu. Meningar med namn ("… har varit onåbar", "<bil> laddar") översätts
  med regler, och datum följer valt språk.
- **NIBE "Status kompressor" (43427)** (#184): statuskoderna 20/40/60/100 (stoppad/startar/går/stoppar) och texter som
  "Running"/"Stopped" tolkas rätt. Förut räknades varje kod över 0 som att kompressorn gick.

## 1.2.62 (2026-11-08)
- **Bil utan batterinivå laddas efter schemat** (#204): saknar bilen batterinivå i Home Assistant (t.ex. Zeekr) men
  har ett påslaget schema eller "klar senast" planeras laddningen som om bilen stod på 20 %. Bilen slutar själv när
  den är full. Förut planerades ingenting och laddboxen pausades efter några procent.
- **Värmepump utan utegivare** (#204): en climate-pump som svarar räknas som levande även utan utetemperatur. Förut
  trodde vakthunden att kontakten var bruten, tvingade 21 °C och visade "Tappat kontakt > 45 min" som status.
- **Ser mätaren elbilen?** En gång per dygn jämförs husets förbrukning under laddtimmar med samma timmar utan laddning.
  Sitter laddboxen bakom en egen mätare drar EnergyWizard inte längre av bilen från husets förbrukning och visar
  varför. (Idé från Energy Pilot.)

## 1.2.61 (2026-11-08)
- **Lampknapparna klarar reläer** (t.ex. Shelly som `switch.*`): tänd och släck går via `homeassistant.turn_on/off`,
  så lampor och reläer kan blandas. Fönstergruppen kan vara en lista med grupper och enskilda lampor, grupper i
  grupper följs hela vägen (nattregeln för en lampa i en undergrupp gällde förut inte) och `skip` utesluter
  ersatta lampor.

## 1.2.60 (2026-11-08)
- **Laddat och vad det kostade** (Bil i appen, Elbil på webben): elbilsladdningens kWh och kronor idag, den här
  veckan och den här månaden, med hur mycket som kom från solen. Från nätet räknas full köpkostnad, från solen vad
  elen annars hade sålts för. Energin räknas från uppmätt effekt (inte laddboxens sessionsmätare), och har loggen
  luckor står det "delvis" i stället för en för låg siffra. (Idé från FTW 0.162.)
- Batteriplaneraren kan simulera att husbatteriet täcker husets egen förbrukning medan elbilen laddar
  (`battery_ev_offload_backtest.py`); beteendet i drift är oförändrat.

## 1.2.59 (2026-11-08)
- **Startar på äldre x86-processorer igen** (#202): NumPy 2.4 kräver x86-64-v2 och tillägget kraschade direkt vid
  start på äldre datorer. Alla images låser nu NumPy till 2.3.
- **Engelska som standard för den som inte har svensk webbläsare**: har installationen inget valt språk följer appen
  och webben webbläsarens språk (svenska om den är svensk, annars engelska). Ett valt språk går som förut före.

## 1.2.58 (2026-11-08)
- **Varför laddar bilen långsammare än planen?** Drar bilen tydligt mindre ström än EnergyWizard beställt i fem
  minuter visas en förklaring överst i appen och på webben: laddboxens lastbalansering eller kretsgräns (Easee),
  laddboxens maxgräns, laddboxens egen anledning eller att det är bilen som begränsar. Går laddboxens gränser inte att
  läsa (Easee: sensorerna är avstängda som standard i Home Assistant) säger texten det och hur man slår på dem.
- **Höll vi planen?** (Historik i appen och på webben): per enhet hur stor del av minuterna elbilen, värmepumpen och
  husbatteriet gjorde det EnergyWizard beställde, idag eller igår, och när de avvek. Inget sparas i skuggläge.
- **Skickade aviseringar** (Notiser i appen, Aviseringar på webben): de senaste 7 dygnens aviseringar med hur det
  gick: skickad, misslyckad (med orsak), avstängd kategori eller ingen mottagare.
- Appens laddschema kunde ge ett JS-fel om det ritades innan bilarna hunnit läsas in.

## 1.2.57 (2026-11-08)
- **Felrapporter säger var felet sitter**: ett programfel i motorn skickar nu kodplatsen (fil, rad och funktion), aldrig
  feltexten, så att det går att rätta utan att fråga användaren.
- **Omstarter av Home Assistant räknas inte som fel**: svar 502/503/504 och avbrott kortare än cirka fem minuter
  loggas som väntan. En token som inte godkänns (401) får ett tydligt eget meddelande.
- **Badtider och eco-golv under appens inställningar** (Effekt), utöver spabadsrutan.
- **Installationer** (utvecklarens sida): nyckeltal, fel grupperade över alla hus, en kompakt rad per hus med filter.

## 1.2.56 (2026-11-08)
- **Badtider för spabadet**: välj vilka dagar och tider ni brukar bada (appens spabadsruta eller Spabad på webben).
  Utanför badtiderna får badet svalna till eco-golvet och värms upp i tid före nästa badtid, på de billigaste
  timmarna. Inga badtider = badet hålls varmt som förut. Kört mot 60 dygns historik i ett hus med välisolerat bad:
  helgbad 10-18 sparar ungefär 25 % med eco-golv 30 °C och 34 % med 25 °C, utan att badet någonsin var kallt vid
  badtidens början (`spa_bath_backtest.py` räknar på det egna huset).
- **Appens framsida** visar inte längre planklockan; den finns under Plan.

## 1.2.55 (2026-11-08)
- **"Klar senast" från Home Assistant** (#200): en valfri `ready_by`-entitet per bil (och `ready_soc`) går före
  veckoschemat, och en ändring räknar om laddplanen direkt. Se README.
- **NIBE via kurvförskjutningen** (#200): utan rumsbörvärde styr EnergyWizard pumpen med värmekurvans förskjutning
  (t.ex. 47011 via nibegw och Nibe Heat Pump), och guiden kopplar den.

## 1.2.54 (2026-11-08)
- **Skonar flashminnet i växelriktare och batterier** (#194): värden i Home Assistant (lägesval och effektbörvärden)
  skrivs inte om de redan stämmer, och inom samma batteriläge skrivs ingen ny effekt förrän ändringen är minst 200 W
  eller 10 %. Håll-vid-liv-skrivningar som vissa batterier kräver (t.ex. Solis tvångsladdning) skrivs som förut.
  Exportgränsen och värmepumpen var redan skyddade.
- **Skonar minneskortet** i tillägget: databasen samlar sina skrivningar i stället för att tvinga ut varje rad till
  kortet (Raspberry Pi med SD-kort, HA Green). Vid strömavbrott kan de sista sekundernas loggrader gå förlorade.

## 1.2.53 (2026-11-07)
- **Värmepumpen står inte som "Vilar" när läget är okänt** (#184): utan kompressorgivare visas bara innetemperaturen.
  Guiden kopplar nu NIBE:s kompressorfrekvens eller kompressorstatus (myUplink, nibe_heatpump), så att flödet visar
  när pumpen går. Statustexter som "on"/"off" läses också.

## 1.2.52 (2026-11-07)
- **Aviseringar till den som är hemma** (valfritt, Inställningar → Aviseringar): aviseringar om huset går till
  telefonerna vars person är hemma enligt Home Assistant (`person.*`). Är ingen hemma går de till alla personers
  telefoner; vet Home Assistant inte var någon är går de till den valda telefonen som förut. Samma regel i motorn och
  i mobilappen.

## 1.2.51 (2026-11-07)
- **Egna laster** (#192): prylar med effektsensor (t.ex. smartpluggar) kan läggas in under `loads:` i installationen.
  De syns som egna rader i "Vad drar strömmen" och räknas bort från det oförklarade (se README).
- **"Vad drar strömmen"** (#191) visar bara elbil, värmepump och spabad om huset har dem.
- **Historiken visas även med ogiltiga givarvärden** (#186): "inf"/"nan" i loggen gjorde att sidan blev tom. Sådana
  värden sparas inte längre, och felrutor på webben visar felkoden även via Home Assistants Ingress.

## 1.2.50 (2026-11-07)
- **Bilvärmen hålls på riktigt**: en sovande Tesla uppdaterar inte sin klimat-entitet, så "på" kunde stå kvar fast bilen
  slutat värma, och då värmdes den aldrig igen. Under timmen värmen hålls begärs nu en färsk avläsning från bilen var
  femte minut (bilens uppdateringsknapp om den finns, annars `homeassistant.update_entity`).
- **Inget falskt fel när bilen vaknar långsamt** (#190): värmekommandot väntar upp till 60 s, och svarar Home Assistant
  ändå inte räknas det som lyckat om bilen står på önskat läge.
- **"Just nu" är samma komponent i appen och på webben**: samma siffror, statusord och riktningar på båda ställena.
- **Aviseringar**: längre tidsgräns mot Home Assistant (#188). **Gallringen** hoppar över loggtabeller som huset inte har (#189).

## 1.2.49 (2026-11-07)
- **Appens framsida visar vad som händer just nu**: ett flöde med sol, nät och batteri till vänster, huset i mitten och
  det som drar el till höger. Varje del har en siffra och ett statusord, och prickarna rör sig åt det håll elen går.
  Rutorna för nät, sol, varmvatten och billigaste timmen, som nu syns i flödet och planen, är borttagna.
- **Planklockans remsa visar hela planen** och går att dra i hela vägen. Förut räckte den bara 12 timmar.
- **"Nu"-knappen i planklockan** ligger inte längre ovanpå Skyline/Klocka-valet.
- **Besparingssensorn i Home Assistant** (`sensor.smartbox_besparing_idag`) finns från dygnets första timme. Förut
  saknades den före lunch, och kortet visade "Enheten hittades inte".
- **Den gamla Streamlit-dashboarden är borttagen** (webben och appen har ersatt den).

## 1.2.48 (2026-11-07)
- **Easee kopplas helt av guiden**: laddboxens serienummer, påslagsbrytaren och alla entiteter (effekt, ström, session,
  livstid, online) hittas oavsett språk och vad boxen heter. Förut kopplades bara status, och utvecklarens boxnamn
  skrevs in åt alla.
- **Easees fasströmmar läses igen** (nyare integration döper dem `state_inCurrentT3` osv.), så bilarnas faser och
  maxström kan läras in.
- **Inga inbyggda laddboxar**: utvecklarens två Easee-boxar (serienummer, entiteter, påslagsbrytare) låg som standard i
  koden. Fasminnet gäller nu per laddbox; förut delade alla boxar samma minne.

## 1.2.47 (2026-11-07)
- **Varning när växelriktaren inte svarar via en FTW-drivrutin** (#184–#186): Översikt visar felet, adressen och vad
  man kan kontrollera, i stället för tomma flikar för sol, batteri och historik.
- **Elbil-knapparna** (#182): förklaring på varje knapp, och "Max"/"Ladda nu" använder bilens maxström
  (`charger.max_a`, annars det inlärda, annars 16 A) i stället för fasta 16 A.
- **Guiden väljer inte elmätarens produktion som solceller**: Tibber Pulses och P1-mätarnas "production" är exporten
  till nätet, inte solen.

## 1.2.46 (2026-11-07)
- **Överstyrningar sparas igen**: långa värden (t.ex. gästladdning) fick inte plats i databasen och föll med ett fel.

## 1.2.45 (2026-11-07)
- **Telemetrin är obligatorisk**: den är ett villkor för att använda EnergyWizard och går inte längre att stänga av.
  Vill du inte dela den ska du inte använda EnergyWizard. Vad som skickas står i README under "Telemetri"
  (utrustning, ungefärliga storlekar, inställningar och feltyper, aldrig namn, adress eller mätvärdeshistorik).
  Valen `telemetry_opt_in` och `anonymous_ping` i tillägget läses inte längre, och det anonyma livstecknet är borttaget.

## 1.2.44 (2026-11-07)
- **Guiden summerar MPPT-modulerna** (#139): hittar den en effektgivare per MPPT-modul (t.ex. Fronius GEN24) föreslår
  den alla moduler summerade i stället för bara den första.

## 1.2.43 (2026-11-07)
- **Flera växelriktare**: den generiska soldrivrutinen kan summera solproduktionen från flera växelriktare
  (`sum_inverters: true`, se README).
- **Elbil-sidan visar laddningens faser och maxström** per bil, och om de kommer från installationen, är inlärda av
  laddningarna eller är standard.

## 1.2.42 (2026-11-07)
- **Ingen falsk sol när batteriet säljer** (#175): korrigeringen för en fastfrusen solgivare räknade all export som
  sol. Nu räknas batteriets urladdning bort först.
- **Flödesbilden** (#177): prickarna till värmepump, varmvatten, elbil och spabad går nu ut från huset.
- **Uppmätt värmepumpseffekt** (#178): "Vad drar strömmen" och COP använder pumpens egen mätning (NIBE lokal,
  HeishaMon) i stället för en uppskattning ur framledningen.
- **Värmepumpen räknar med tidstariffen** (#179): billiga och dyra kvartar rangordnas och jämförs på spotpris plus
  tidstariff, så att kvarten före 22 inte räknas lika billig som kvarten efter.
- **Effekttariffens höglasttid går att ställa in** (#180): den var hårdkodad till ett nätbolags tider. Välj egna tider,
  tidstariffens tider eller ingen höglasttid under Inställningar → Elpris och avgifter. Raden "Aktuell effekttariff"
  visas bara för den som har en tariff inställd.

## 1.2.41 (2026-11-06)
- **Tomt batterifält blir inte längre 0**: ett tömt maxnivå-, effekt-, storleks- eller verkningsgradsfält som sparats
  som 0 eller tomt används som standardvärde. Annars kunde maxnivå 0 stoppa all laddning. (Samma fel som FTW
  rättade i 0.158.3, hittat genom att bevaka deras ärenden.)

## 1.2.40 (2026-11-06)
- **Samma hus räknades två gånger**: motorn, webben och appen skriver i samma inställningsfil, och utan lås kunde
  en av dem skriva tillbaka en gammal bild så att installations-ID:t försvann. Då dök huset upp som ett nytt på
  Installationer. Skrivningarna är nu låsta och läses färskt från disk, och ID:t har en egen reservfil.
  Insamlaren slår ihop befintliga dubbletter (samma utrustning, det gamla tystnade innan det nya dök upp).

## 1.2.39 (2026-11-06)
- **Anonymt livstecken**: med telemetrin avstängd skickas en gång per dygn bara det hashade installations-ID:t och
  versionen, så att alla installationer syns i räkningen. Inget om utrustning, hus eller mätvärden. Stängs av helt
  med det nya reglaget `anonymous_ping` (README och DOCS beskriver exakt vad som skickas).

## 1.2.38 (2026-11-06)
- **Hemskärmen putsad**: lugnare rutor utan tunga ramar, enheten direkt efter siffran, bilarna som brickor med
  laddstapel, beslutsraderna på två rader i stället för att klippas, och Skyline/Klocka-knapparna i kortets hörn.
  Med stor text i telefonen finns ett extra kompakt steg, så att allt ryms utan scroll på en vanlig telefon.

## 1.2.37 (2026-11-06)
- **Fler batterier kan styras** (ej provade på riktig hårdvara – börja i skuggläge):
  - **Sonnen** via integrationen sonnenbatterie: manuellt läge och laddning/urladdning med vald effekt.
  - **Victron ESS** via hass-victron: nätets börvärde (+ laddar från nätet, − laddar ur).
  - **Kostal Plenticore**: "håll" – lägsta laddnivå sätts till nuvarande så att batteriet sparas till dyra timmar.
  - **Pixii, Deye och Sigenergy** direkt via Sourcefuls drivrutiner: nytt val i installationsguiden, "Låt EnergyWizard
    styra batteriet".
- SMA och Alpha ESS läses fortfarande (styrning kräver SMA:s Modbus-register respektive Alpha ESS molnschema).

## 1.2.36 (2026-11-06)
- **Batteriet hölls tillbaka av en elbil som inte var inkopplad** (#174): batteriet räknar nu elbilen som laddande först
  när laddboxen faktiskt drar ström. Manuell tvångsladdning väntar tills kabeln sitter i, och kontaktorskyddet släpper
  när bilen inte är inkopplad. Laddboxstatusen `not_connected` (Garo m.fl.) känns igen överallt i motorn.
- **Batteriets effekt med två givare** (#139): batterier med en givare för laddning och en för urladdning (t.ex. Fronius
  GEN24 "Storage charging/discharging power") väljs av installationsguiden i stället för en ensam, ibland fel, effektgivare.

## 1.2.35 (2026-11-06)
- **Ny hemskärm i appen**: planklockan är större och texten i den skalar med klockan (krympte förut med stor text tills
  texten trängdes ut över ringen). Under beslutsraderna finns sex kompakta rutor i stället för två stora: **Inne**
  (temperatur, mål, värmepumpens läge), **Nät** (köper/säljer, pris), **Sol** på dagen eller **Varmvatten** på natten,
  **Batteri** (om du har ett) eller **Billigast** härnäst, **Sparat** (tryck för idag/7 d/månad) och **Idag** (förbrukat).
  Bilarnas laddnivå visas på en rad. Allt ryms utan scroll på en vanlig telefon.

## 1.2.34 (2026-11-06)
- **Guiden kommer ihåg alla val** (#173): även elmätarvalen (hela huset, säljeffekt, annan byggnad), kryssrutorna för
  generisk styrning och direkt anslutning till växelriktare (drivrutin, IP-adress, port, roll) fylls i som du lämnade dem.

## 1.2.33 (2026-11-06)
- **Guiden kommer ihåg dina val** (#173): vilka bilar och enheter du kryssat i, bilarnas namn och batteristorlek sparas
  när du sparar (eller laddar ner filen) och fylls i igen nästa gång, även efter en ny skanning. Förut stod guidens
  förval där igen (alla ikryssade, gissade namn).

## 1.2.32 (2026-11-06)
- **Elmätaren hittas** (#171): en Tibber Pulse med bara köp- och säljeffekt (utan spänning och ström per fas) känns igen
  av installationsguiden. I guiden kan man också välja en egen sensor för **säljeffekt**, så att export syns även när
  mätarens effektsensor bara visar köp.
- **Skuggläget** (#172) visar inte längre skrivningar till en Thermia/Husdata-pump som inte har någon adress.

## 1.2.31 (2026-11-06)
- **Försäljning visades som köp** (#171): Tibber Pulse med nyare entitetsnamn (efter hemmets namn) hittades bara via
  spänning × ström, som saknar tecken. Nu hittas Pulsens köp- och säljeffekt oavsett namn, och loggen säger vilka
  givare elmätaren använder.
- **Effektgivarnas tecken i webben**: Inställningar har reglage för att vända tecknet på nätets och batteriets effekt.
- Laddnivå "inf %" visas inte längre; ogiltiga tal (inf/nan) från Home Assistant räknas som saknade.

## 1.2.30 (2026-11-06)
- **Orimlig batterieffekt** (#139): visar batteriets effektgivare mer än ett husbatteri kan (t.ex. 18,2 kW) räknas den
  inte in i husets förbrukning, och Översikt säger att troligen fel givare valts (t.ex. energi i kWh) och var man
  väljer rätt.

## 1.2.29 (2026-11-06)
- **Aviseringar till eget skript** (#170): mottagaren av aviseringarna kan vara ett skript i Home Assistant (får
  variablerna `title` och `message`) eller vilken notify-tjänst som helst, inte bara en telefon.
- **Nya formulär på webben**: listor, fält och kryssrutor har fått samma formspråk som korten (rundade, egen pil, tydlig
  fokusring), i ljust och mörkt tema.
- **Lugnare logg när Home Assistant är nere**: motorn pausar 30 s efter ett misslyckat försök i stället för att varje
  avläsning försöker igen, felraden skrivs vid tredje försöket och sedan var tionde, och nätverksfel skrivs utan
  felspår.
- Bilens uppdateringsknapp (t.ex. Leaf) trycks i bakgrunden; att tillverkarens moln svarar långsamt är ingen varning.
- Appens felrapporter tar med var felet uppstod.

## 1.2.28 (2026-11-06)
- **Senaste skanningen visas alltid** (#168): resultatet av "Skanna mitt Home Assistant" sparas i installationen och
  visas med datum och tid när man kommer tillbaka till Inställningar, även efter att man sparat och även när Home
  Assistant-appen startat om.
- README: tydligare om solcellsexporten (#169). Vid minuspris regleras bara exporten ner till noll; över 0 kr exporteras
  överskottet som vanligt.

## 1.2.27 (2026-11-06)
- **Webben hämtar alltid senaste versionen** (#167): app.js och style.css länkas med versionsnummer. Home Assistant-appen
  på iOS kunde visa en gammal, sparad stilmall (t.ex. den grå mobilmenyn) trots att en ny version var installerad.
- **Husets förbrukning negativ** (#139): Översikt visar alltid delarna (sol + nät − batteri) när huset räknas negativt,
  så att man ser vilken givare som visar fel. Knappen för att vända batteriets tecken visas när den hjälper.

## 1.2.26 (2026-11-06)
- **Appen hoppade upp till toppen** när man scrollade (stor text): uppdateringen var 5:e sekund ritade om sidan med
  scrollen överst. Scrollpositionen behålls nu.
- **Klockan vreds av misstag** när man scrollade med fingret på den: ett lodrätt drag scrollar nu sidan, och tiden väljs
  först när man vrider eller trycker.

## 1.2.25 (2026-11-06)
- **Inga inbyggda pumpadresser** (#165): Thermia/Husdata läses bara när pumpens adress är angiven (PUMP_IP eller
  `heat_pump.connection.modbus_host`). Förut försökte motorn mot två fasta adresser och skrev ett fel varje minut hos
  den som inte har Husdata.
- **Batteriets tecken** (#166, #139): räknas husets förbrukning negativ men går ihop med omvänt tecken på batteriets
  effekt, föreslår Översikt "Vänd tecknet på batteriets effekt". Ändringen gäller direkt, utan omstart.
- **Mobilmenyn** (#164): den utfällda menyn på webben har tät bakgrund och full textfärg - var grå och svårläst i ljust tema.

## 1.2.24 (2026-11-06)
- **NIBE via myUplink hittas** (#162): entiteter med bara myUplinks parameternummer i namnet (t.ex. "Utomhustemperatur
  (40004)") känns igen, även när enheten inte heter något med värmepump. Installationsguiden sa felaktigt "Husdata
  redan ansluten" när innetemperaturen kom från rumsgivare. Det kräver nu att Husdata faktiskt är vald och att pumpen
  loggar framledning.
- **Skanningen finns kvar** (#163): resultatet av "Skanna mitt Home Assistant" ligger kvar i en timme när man byter flik
  eller när Home Assistant-appen laddar om sidan, tills man sparar.
- Priskällekortet kunde ge ett skriptfel om man bytte flik medan det laddade.

## 1.2.23 (2026-11-06)
- **Dolda flikar** (#161): webben döljer flikarna Spabad, Elbil, Värmepump och Solceller när installationen saknar den
  utrustningen (Solceller ligger kvar om det finns ett husbatteri). Egna flikar kan döljas med `ui: hidden_tabs:
  [prognos, temperaturer]` i house_config.yaml. En dold flik öppnar Översikt.
- **Batteriets effekt i flödesbilden** (#160): batterirutan på Översikt visar effekten, t.ex. "Batteri · 850 W".

## 1.2.22 (2026-11-06)
- Sponsringspåminnelsen berättar vad utvecklingen kostar (runt 1 000 € de senaste veckorna) och visas en gång till
  den här månaden, på installationens språk. Den kan som förut stängas av i inställningarna.
- Appen: sponsringsrutan visas som en ruta mitt på skärmen (låg tidigare längst ner på sidan) och går att scrolla
  med stor text.

## 1.2.21 (2026-11-06)
- **NIBE via Home Assistants myUplink-integration** (#158): ny drivrutin som läser värmepumpen via integrationens
  entiteter. Installationsguiden kopplar dem själv via NIBE:s givarkoder (BT1 ute, BT2 framledning, BT3 retur,
  BT7/BT6 varmvatten, BT50 rum) och gradminuter. För att styra väljer man rumsbörvärdet själv.
- Installationsguiden tog en nätverksskanners post för pumpens nätverkskort (t.ex. NetAlertX, "Nibe") för
  värmepumpen. Nu krävs temperaturgivare eller en climate-entitet.
- **Värmepump-flikens mätvärden** (#159): kortet "Just nu" på webben med kompressor, frekvens, el in, framledning,
  retur och COP. NIBE S1155/S1255 lokalt ger frekvens, el och uppmätt COP ur pumpens energilogg.

## 1.2.20 (2026-11-06)
- Appen med mycket stor text: när en flik måste scrolla fick planlistan på Plan-fliken bara 18 px höjd. Alla delar
  får nu sin naturliga höjd när sidan scrollar.

## 1.2.19 (2026-11-06)
- **Appens hemskärm med stor text**: med förstorad text i telefonen klipptes planklockans staplar av och sol- och
  nätrutorna kläms ihop bakom besparingsraden. Nu krymper planen stegvis, rutorna har en minsta höjd, och får det
  ändå inte plats går hemskärmen att scrolla i stället för att något göms. Provat i 411×914, 411×800 och 360×640 med
  normal och förstorad text, både klocka och Skyline.

## 1.2.18 (2026-11-06)
- **Kallt inne räknas först efter 30 minuter**: notisen "Kallt inomhus!" och värmetvånget oavsett elpris kommer
  först när det varit kallt i 30 minuter i följd. En vädring eller öppen dörr nära givarna (t.ex. 21,8 → 14,6 °C
  under några minuter) ger ingen notis och ingen dyr värme.

## 1.2.17 (2026-11-06)
- **Färdigbyggd bild**: Home Assistant hämtar tillägget som en färdig bild (amd64 och aarch64) i stället för att
  bygga det på din maskin. Uppdateringar går på någon minut och misslyckas inte längre på maskiner med lite minne.
  Den här uppdateringen är den sista som byggs på din maskin, och den kan ta en stund.

## 1.2.16 (2026-11-06)
- **Innetemperaturen räknade in utegivaren** (#149): en utegivare som var förkryssad bland innegivarna gav t.ex.
  (18,2 + 2,4) / 2 = 10,3 °C och larm om kallt hus. Utegivare räknas aldrig in i innetemperaturen. I givarlistan visas
  de som utegivare utan kryssruta, och de går inte att spara som innegivare.
- **Rumsbörvärdet till NIBE, myUplink och HA-climate** (#151): skickades i tiondelar (200 i stället för 20,0 °C) och
  avvisades. Skickas nu i °C. Thermia får exakt samma registervärde som förut.
- **NIBE lokalt** (#152): en lyckad skrivning rapporterades som misslyckad när pumpen (S1255) svarar med hela punkten.
  Ett avvisat anrop loggar nu statuskoden (t.ex. HTTP 403 när ändringar inte är tillåtna i pumpens meny 7.5.15).
- **Utan spabad** (#156): inga spabadsrader i loggen och inga anrop till spadrivrutinen.
- **Loggen live** (#154): Logg-fliken på webben uppdateras var 10:e sekund (kan stängas av).
- Pumpar som sparar börvärdet i hela grader (Thermia) fick samma börvärde omskrivet varje minut när det var en halv
  grad. Avrundningen godtas nu.

## 1.2.15 (2026-11-06)
- **Bilvärmen håller temperaturen**: när du startat värmen från appen och bilen själv stängt av klimatet kollar
  EnergyWizard 10 minuter senare. Har kupén svalnat mer än 1 °C under önskad temperatur startas värmen igen
  (högst 3 gånger, i en timme från knapptrycket, och inte om bilen kört iväg).
- **Thermia via ThermIQ** (#153): ny drivrutin för ThermIQ-MQTT/ThermIQ-ROOM via ThermIQ:s HA-integration. Den läser
  inne-, ute-, framlednings-, retur- och varmvattentemperatur samt gradminuter, kompressor och larm, och styr
  rumsbörvärdet och varmvattnets start/stopp. Installationsguiden känner igen den själv. Den är inte provad mot en
  riktig pump än, så kör i skuggläge först.

## 1.2.14 (2026-11-06)
- **Minutloggen tappades** hos hus vars drivrutin rapporterar på/av som sant/falskt: databasen vägrade raden
  (DatatypeMismatch). Sådana värden sparas nu som 1/0.
- Installationer visar bara fel som **fortfarande uppstår**: ett kvarstående fel rapporteras varje timme, och det som
  inte setts på 75 minuter eller hör till en äldre version försvinner.

## 1.2.13 (2026-11-06)
- **Färre falsklarm**: tillfälliga nätverksfel (Home Assistant eller väderprognosen svarade inte en stund) är
  varningar, och på Installationer visas de grått för sig – bara riktiga fel visas i rött.
- FTW-drivrutinerna provas automatiskt mot Sourcefuls enhetssimulator vid varje ändring (Sungrow: läsning och
  styrning fungerar; sju av åtta läser rätt).

## 1.2.12 (2026-11-06)
- **NIBE lokalt REST fungerar mot riktiga pumpar** (#145, felanalys av larsfrisk): läsningen kraschade med "Bad file
  descriptor" när pumpen stängde anslutningen efter svaret. Tomt produktnamn (S1255) godtas och modellens register
  väljs, felets typ syns i loggen, och varmvattentemperaturen läses för alla värmepumpar (inte bara Thermia).
- **Bilens faser och maxström lärs in** av laddningarna när installationen inte anger dem.
- **Installationsguiden**: batteri eller växelriktare utan Home Assistant-integration kan väljas via en FTW-drivrutin.
- **Skyline**: avläsningen ligger ovanför staden, höjden anpassas efter huset, billigaste och dyraste timmen märks,
  och soluppgången syns på natten.

## 1.2.11 (2026-11-06)
- **Gästbil** (#131): ladda en bil som inte är din på valfri laddbox – ange kWh och ev. klar-tid i appen (Bil → Gästbil),
  så laddas de billigaste timmarna fram till dess, alltid under säkringen. Avslutas när kabeln dras ur.
- **Effektavgift efter månadens högsta timmar** (#141): för Norges effektledd och nätbolag som tar betalt efter snittet
  av de högsta timmarna i trappsteg (Elförbrukning → Effektavgift efter högsta timmar).
- **Fler batterier kan styras**: färdiga förinställningar för GoodWe, SolarEdge med batteri, Sungrow (mkaiser),
  Huawei LUNA2000, Tesla Powerwall och Enphase – installationsguiden fyller i dem själv. Kör i skuggläge först.
- **Sourcefuls FTW-drivrutiner** (`driver: ftw`): 93 drivrutiner för växelriktare, batterier och mätare som läser
  direkt från enheten utan Home Assistant-integration (t.ex. Pixii). Läsande; styrning slås på per verifierad enhet.
- **Batteriet säljer aldrig när export är avstängd**: urladdningen begränsas till det huset köper.
- Huawei-batterier hittas av installationsguiden (räknades förut som en telefon), och en Powerwall tas inte för en bil.

## 1.2.10 (2026-11-05)
- **Planvyn Skyline** överst på förstasidan i appen och på webben (förvald), med planklockan som val. Dygnet som en
  stad: högt hus = dyr el, tända fönster = huset använder el, solen över staden, bilarna på vägen, batteriet i vattnet.
- **Besparingen räknas mot ett vanligt hushåll** (toppar morgon och kväll) och inklusive moms, i appen, på webben och
  i HA-sensorn. Rättvisare än det tidigare jämna dygnssnittet.
- **Färre falska fel**: en enstaka timeout mot Home Assistant är en varning (fel först efter tre i rad), och loggen
  visar rätt källa och felförloppet en gång.
- Appen: "alla rum" fungerar, raderna i "vad görs nu" ligger i linje, rätt moms i appens priser.
- Webben: landet syns på varje installation, dygnsgrafen är läsbar i mobilen.

## 1.2.9 (2026-11-05)
- **Laddschemat för hela veckan på webben** (#142): Elbil-fliken har en rad per veckodag (som appen), en knapp för
  samma schema alla dagar, och visar vilket mål planen räknar med just nu ("fredag 07:00 · 100 %"). Översikten
  skriver veckodagen.
- **Planklockan på förstasidan** i appen och på webben: en kvart per streck, färg när batteri eller bil gör något,
  solprognosen som krans, dra visaren för att se pris och plan vid valfri tid, och de närmaste 12 timmarna under.
- **Graferna i appens Historik** har tunna linjer och en skala (förut breda band utan värden).
- **Sourcefuls FTW-drivrutiner kan köras** (lua_host.py): alla 54 host-funktioner finns, 91 av 93 drivrutiner startar
  (de två sista kräver inloggning/nyckel). Verifierad mot en riktig Shelly 3EM. Inte inkopplad i motorn än.

## 1.2.8 (2026-11-05)
- **Logg för hela installationen**: allt EnergyWizard läser in, bestämmer (med orsak), skickar till enheterna,
  aviserar och får för fel - från motorn, appen och webben. Webben: sidan Logg (filter, sök, ladda ner 2 dygn som
  supportfil att bifoga i en issue). Appen: Inställningar → Logg. Sparas i ditt hus i 14 dygn, bara ägaren ser den.
- **Bilens värme visas inte som "på" när man kör**: klimatet räknas som förvärmning bara när bilen står hemma och
  inte är i körläge (`shift_state` om bilen har det).

## 1.2.7 (2026-11-05)
- **Inga bilnamn, rum eller personer från ett annat hus**: laddschemat och klimatschemat byggs av dina egna bilar
  (förut fasta "nissan"/"tesla" - andra bilars scheman kunde ignoreras), rummen är dina valda innegivare,
  hälsningen använder bara namn och fraser du själv lagt in, och "Visa som familj" i stället för ett namn.
- **Hushållsmaskiner** (t.ex. tvättmaskin) väljs i installationen (`appliances`), inget fast märke.
- Attributen i Home Assistant (elbil solel) heter efter dina bilar.

## 1.2.6 (2026-11-05)
- **Varning när husbatteriet inte gör som det blir tillsagt**: avviker batteriet från kommandot i mer än 5 minuter
  (t.ex. laddar fast det ska ladda ur) syns en röd ruta i appen och på webben, och en notis skickas.
- **Alla notiser går att stänga av** per kategori (elbil, batteri, sol, värmepump, spabad, elpris, effekt, lampor,
  system, övrigt) under Inställningar → Notiser, på webben och i appen.
- **Egen färg när batteriet laddar ur och säljer** till nätet, skilt från urladdning för eget bruk.
- Upptäckten föreslår inte batteri för en växelriktare som saknar batteri (0 % och 0 W).

## 1.2.5 (2026-11-05)
- **Inga främmande lampnotiser** (#134): appen bevakade och styrde lampor som inte hör till ditt hus. Nu bara lampor du
  själv valt; utan val syns inga lampknappar. "Exportgräns offline" larmar bara om växelriktaren går att begränsa.
- **Husets förbrukning** (#139): batteriets och elmätarens effekt räknas om från kW till W enligt sensorns enhet. Blir
  huset ändå kraftigt negativt visas 0 och loggen säger vilken givare som ser fel ut.
- **Tidslinjen visar bara dina bilar** (#136), med rätt namn, och Spabad/Värmepump bara om de finns.
- **Generisk laddbox (t.ex. Garo) ger laddeffekt** (#140): `power_kw` eller `power` används i översikt, tidslinje och
  basförbrukning.
- **NIBE lokalt REST i tillägget** (#138): användarnamn, lösenord och certifikat-pin går att fylla i under Konfiguration.
- **Spabad (Gecko), SolarEdge och väder** läses ur installationen - inga entitetsnamn från ett annat hus i koden.

## 1.2.4 (2026-11-05)
- **Tillägget hämtar alltid senaste koden**: förut kunde Home Assistant återanvända en gammal byggd kopia trots ny version
  (därför syntes vissa rättningar, t.ex. #125, inte förrän man byggde om själv).
- **Installationsguiden sparar även när en vald enhet saknar givare** (#127) - förut "'NoneType' object has no attribute 'get'".
- **Inne-/utetemperatur utan värmepump** (#128): de valda givarna används även när ingen värmepump styrs, utetemperaturen
  tas från den valda utegivaren om pumpen inte har någon, och Temperaturer-sidan visar dina valda rumsgivare.
- **Huvudsäkringen från installationen** (#129): `fuse.main_fuse_a` används i stället för standardvärdet 25 A.
- **Fasströmmar i ampere** (#130) på Elförbrukning, skalade mot huvudsäkringen - gul från 80 %, röd över säkringen.

## 1.2.3 (2026-11-04)
- **Utan spabad syns inget spabad** (#122, #123): ingen spa-bevakning, inga "spabad frånkopplat"-meddelanden och inga
  spabeslut när inget spa är valt. Översiktens bild visar bara installationens bilar och spa.
- **Välj vilken telefon som får aviseringarna** under Inställningar (#123) - förut den första telefonen i HA.
- **Husets förbrukning räknar med batteriet** (#125): sol + nät - batteri, i översikten och historiken.
- **System-fliken**: inget fel när Watchtower saknas (#121) - visar hur man uppdaterar i stället.
- Motorn: bilar och laddboxar läses helt ur installationen (inga inbyggda bilar kvar).

## 1.2.2 (2026-11-04)
- **NIBE S1155/S1255 via pumpens lokala REST-API** (tack lazgeo, #115): läser temperaturer och kompressorstatus,
  certifikatet kontrolleras innan lösenordet skickas. Styrning är avstängd tills man slår på den. Se docs/nibe-local-rest.md.
- En felaktig inställning för en enhet stoppar inte längre hela motorn: felet loggas och motorn kör vidare utan just den enheten.

## 1.2.1 (2026-11-04)
- **Nätet visades fel med Tibber Pulse när man säljer solel** (#114): pulsens fasström saknar tecken, så export syntes
  som köp. Har pulsen köp- och säljeffekt används de nu; installationen hittar dem själv.
- **Loggningen föll varje minut** med en generisk värmepump (`invalid input syntax for type smallint: "auto"`, #112).
- **Elbil-sidan visade Tesla och Nissan** för alla (#113): bilarna kommer nu från installationen, i webben och appen.
- Mobilappen startade inte efter 1.2.0 i vissa fall (pymodbus) - rättat. Lås/luckor i webben fungerar igen.

## 1.2.0 (2026-11-04)
- **Öppna webbgränssnittet fungerar inuti Home Assistant** (Ingress, issue #118): även via Nabu Casa, https och HA-appen,
  och HA:s inloggning gäller. EnergyWizard får en egen panel i sidomenyn.
- Nya installationer kraschade på loggningen varje minut (`temp_garage`) och skickade aviseringar till fel telefon - rättat.
- Givare inne/ute, bilar, laddboxar och telefoner väljs i installationen; inget är inbyggt för ett visst hus.
- Två växelriktare/batteribankar räknas som ett batteri; fritt val av elmätare.
- Tidstariff, Solax Gen2, HeishaMon-paus via kurvan, telemetri med fel som blir GitHub-ärenden.
- Robotgräsklipparen är borttagen.

## 1.1.0
- Startskriptet med samma mapplayout som bilden.
