# EnergyWizard (Supervisor-tillägg)

Kör EnergyWizards huvudmotor (`smartbox`) direkt i Home Assistant OS/Supervisor
- ingen docker-compose, ingen extern databas att sätta upp själv.

## Vad detta tillägg är - och inte

Det här paketerar **bara huvudmotorn**, de beslut som styr elbil, värmepump,
solcellsexport, spabad och huvudsäkring. Mobilappen (`ewapp`) och
dator-/surfplattevyn (`webdashboard`) ingår INTE än - de kräver fortfarande
den vanliga docker-compose-driften (se huvudrepots README). Det betyder bland
annat att motorns **engångs-notis om att konfigurationen är tom** (den som
dyker upp i Home Assistants eget notisfält) idag pekar mot en webdashboard-
adress du inte har om du bara kör det här tillägget - redigera
`house_config.yaml` direkt istället (se nedan) tills gränssnitten också
paketeras.

## Kom igång

1. Installera tillägget.
2. Öppna **File editor**- eller **Samba**-tillägget (eller SSH:a in) och
   redigera `/addon_configs/<tilläggets id>_smartbox/house_config.yaml` -
   en helt tom fil (bara `house_id: mitt-hus`) är ett giltigt, testat
   utgångsläge där allt bara blir overksamt istället för att krascha. Se
   `config/house_config.example.yaml` i huvudrepot för hur en riktig,
   ifylld fil ser ut.
3. Starta om tillägget efter att du ändrat filen.
4. Följ loggen (fliken **Log**) - samma utskrifter som
   `docker compose logs -f smartbox` ger i den vanliga driften.

## Home Assistant-åtkomst

Tillägget pratar med Home Assistants Core API via Supervisorns egen proxy
(`homeassistant_api: true` i konfigurationen) - du behöver INTE klistra in
någon egen åtkomsttoken eller IP-adress, till skillnad från den fristående
docker-compose-driften.

## Databas

En lokal Postgres startas inuti tillägget vid uppstart och sparas i
tilläggets egen, bestående konfigurationsmapp (`/config/pgdata` i
containern) - den försvinner inte vid omstart, men är en egen databas,
skild från en eventuell Postgres du redan kör för den vanliga driften.

## Telemetri (valfritt, av som standard)

Se huvudrepots README för exakt vad som skickas om du slår på
`telemetry_opt_in` i tilläggets inställningar.

## Overifierat än

Det här tillägget är byggt och testat att starta fristående i Docker, men
**aldrig körts mot en riktig Home Assistant Supervisor-installation** -
jag saknar en HAOS-maskin att testa "Lägg till repository"-flödet,
Supervisorns egen validering av `config.yaml`, och den riktiga
`homeassistant_api`-proxyn mot. Fungerar det inte som förväntat: öppna ett
GitHub-ärende med loggen från **Log**-fliken.
