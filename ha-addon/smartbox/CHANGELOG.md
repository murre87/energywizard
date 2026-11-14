# Ändringar

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
