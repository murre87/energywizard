# EnergyWizard (Supervisor-tillägg)

Kör EnergyWizards huvudmotor (`smartbox`) direkt i Home Assistant OS/Supervisor
- ingen docker-compose, ingen extern databas att sätta upp själv.

## Vad som ingår

Tillägget kör allt i en och samma container:

- **Huvudmotorn** (`smartbox`) - besluten som styr elbil, värmepump,
  solcellsexport, spabad och huvudsäkring.
- **Webdashboard** på port **8503** - dator-/surfplattevyn med
  entitetsväljaren. Knappen **Öppna webbgränssnitt** på tilläggets sida går hit.
- **Mobilappen** (`ewapp`) på port **8502** - öppna
  `http://<din-HA-adress>:8502` i mobilen och lägg den på hemskärmen.

Gränssnitten nås direkt på värdens portar, precis som i docker-compose-driften
(inte via Home Assistants sidomeny/ingress). Motorns engångs-notis om tom
konfiguration pekar därför nu rätt, mot `http://<din-HA-adress>:8503`.

## Kom igång

1. Installera tillägget.
2. Starta tillägget och klicka på **Öppna webbgränssnitt**. Första gången öppnas en
   startguide: välj ett lösenord (eller sätt `dashboard_password` under
   **Konfiguration**). Anslutningen till Home Assistant sköts av tillägget själv.
3. Under **Inställningar** hittar entitetsväljaren dina prylar. Kryssa i det du har och
   tryck **Spara och starta**. Konfigurationen sparas i
   `/addon_configs/<tilläggets id>_smartbox/house_config.yaml`, och motorn läser in den
   av sig själv.

Kraschar ett gränssnitt startas det om efter 5 sekunder, utan att motorn
påverkas. Dör motorn startar Supervisor om hela tillägget.

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

## Telemetri (alltid på i det här tillägget)

Telemetrin är alltid påslagen i tillägget och har ingen avstängning (sedan
1.2.45). Vad som skickas står i huvudrepots README under "Telemetri":
utrustning, ungefärliga storlekar, inställningar och feltyper, aldrig namn,
adress eller mätvärdeshistorik. Vill du inte dela det, använd inte tillägget.
Koden är fri under AGPL-3.0: du får ändra den, även ta bort telemetrin, och
använda och sprida den ändrade versionen enligt licensen. De gamla valen `telemetry_opt_in` och `anonymous_ping` läses
inte längre.

## Flottvy Installationer (valfritt, support)

Om du har fått stats-URL och token från utvecklaren kan du under **Konfiguration**
sätta `telemetry_stats_url` och `telemetry_stats_token`. Efter omstart syns menyn
**Installationer** i webben (anonyma hus och felgrupper). Det är din egen
installation — du loggar inte in någon annanstans. Se `docs/support-access.md`.

## Kända begränsningar

- Sidan **System** i webdashboard visar "Kunde inte nå Watchtower". Uppdateringar
  sköts av Supervisor i den här driftformen, inte av Watchtower.
- Entitetsväljaren sparar inte `house_config.yaml` själv, den ger dig en fil
  att ladda ner och lägga på plats (steg 4 ovan).

## Uppdateringar

Från version 1.2.17 hämtar Home Assistant en färdigbyggd bild (`ghcr.io/murre87/energywizard`, amd64 och aarch64)
i stället för att bygga tillägget på din maskin. En uppdatering tar då någon minut i stället för en lång byggtid, och
misslyckas inte på maskiner med lite minne. En ny version visas i Home Assistant först när bilden för den finns.

## Overifierat än

Version 1.1.0: startskriptet är kört med samma mapplayout som bilden -
Postgres initieras, motorn startar, båda gränssnitten svarar, inloggning med
`dashboard_password` fungerar, webdashboard når mobilappen internt, och ett
gränssnitt som kraschar startas om. Själva bilden byggs och röktestas
dessutom i CI (`.github/workflows/tester.yml`, jobbet `ha-tillagg`). Tillägget har
däremot
**aldrig körts mot en riktig Home Assistant Supervisor-installation** -
jag saknar en HAOS-maskin att testa "Lägg till repository"-flödet,
Supervisorns egen validering av `config.yaml`, och den riktiga
`homeassistant_api`-proxyn mot. Fungerar det inte som förväntat: öppna ett
GitHub-ärende med loggen från **Log**-fliken.
