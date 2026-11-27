# Uppdelning av EnergyWizard: plan och logg

Underlag: *Arkitektur- och Migreringsplan för EnergyWizard* (Emil, 2026-11-27). Beslut för genomförandet:

- **Ingen Rust.** Uppdelningen görs i Python. Rust kan komma senare, och då för en liten, väl avgränsad del (säkerhetsskydden), inte för optimeringen.
- **Delarna:** Core (motor, API, säkerhetsspärrar, databas), drivrutiner, planering och ML, webb. Nativa appar är ett framtida spår.
- **Privata repon är tillåtna.** Åtkomst: `lazgeo` och Cursor-boten får tillgång till det privata. Övriga som skrivit kod i delar som blir privata får skriva avtal med Emil innan koden flyttas.
- **Synligheten avgörs sist.** Det tekniska arbetet är detsamma oavsett om en del är publik eller privat, så varje steg görs med allt publikt tills avtalen finns.
- **Inget får gå förlorat.** Varje del som flyttas jämförs först sida vid sida med den gamla (`smartbox/parity.py`) och byts bara när skillnaderna är noll. Planeringen får aldrig stoppa styrningen: Core fortsätter med senaste giltiga plan eller säkra standardvärden om planeringen inte svarar, och skyddsspärrarna (säkring, kompressor) ligger kvar i Core.

## Steg

| # | Steg | Status |
| --- | --- | --- |
| 1 | Kontrakt för planerarens överlämning (beslut och laddplan) + paritetsverktyg, utan att flytta kod | klart (`contracts/`, `smartbox/contracts.py`, `smartbox/parity.py`) |
| 2 | Kontrakt för batteriplanen och för drivrutinernas state och kommandon | |
| 3 | Delat tillstånd i `main.py` (överstyrningar, cacher, globaler som planeringen läser eller skriver) görs uttryckligt i kontraktet | |
| 4 | Planeringen som egen process i samma image (Python), jämförd med den gamla i paritetsverktyget; Core faller tillbaka på senaste plan | |
| 5 | Drivrutinerna till eget repo, med mall och kontraktstester | |
| 6 | API i Core (REST/WebSocket); appen och webben flyttas över ett område i taget, med den gamla vägen kvar tills den nya är verifierad | |
| 7 | Release-kanaler (stable/dev), synlig version och versionskoll | |
| 8 | Flytta det som får vara privat (efter avtal) | |

## Risker att bevaka

- **Delat tillstånd.** `main.py` (3 250 rader) delar variabler, överstyrningar och cacher mellan delarna. Allt som planeringen läser eller skriver måste in i kontraktet innan koden flyttas (steg 3).
- **Nya felvägar** när delar pratar över HTTP: tidsgränser, planeringen nere, gammal plan. Core ska alltid ha ett säkert beteende.
- **HA-tillägget** kör normalt en container per tillägg: delarna körs som processer i samma image där.
- **Upphovsrätt och licens.** Koden är AGPL-3. Bidragsgivare (bland andra `lazgeo`, `flebbhue`, Michal Koláček, Jonatan Åkerlind) behåller upphovsrätten till det de skrivit. Avtal ska finnas innan deras kod ligger i ett privat repo eller levereras som körbar fil utan källkod. FTW-härledda AGPL-drivrutiner (`smartbox/ftw_drivers/`) får inte hamna i ett privat repo.
