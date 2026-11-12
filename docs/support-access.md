# Supportaccess till andras installationer

## Vad FTW gör ([srcfl/ftw](https://github.com/srcfl/ftw))

Community-felsökning (Discord) bygger på att användaren skickar version, inställningar och skärmdumpar. Deras [SUPPORT.md](https://github.com/srcfl/ftw/blob/master/SUPPORT.md) säger uttryckligen att remote-felsökning av en *live*-anläggning **inte** ingår i community-stödet.

Starkare access finns i lager:

| Lager | Vad admin ser | Kräver |
| --- | --- | --- |
| Fleet-statistik | Anonym version/drivrutiner/hälsa | Alltid (aggregat) |
| `ftw support` | Redigerad lokal supportfil | Användaren skickar filen |
| Cloud-tunnel | Ägarens telefon når boxen | Ägaren parar Cloud |
| Readable Cloud-kopia | Live flöden/plan (~48 h) | Ägaren ger Sourceful läsrätt |
| `support`-agent (“Get help”) | Live/logg/config/diag, tidsbegränsat | Ägaren godkänner per ärende |

Ingen tyst backdoor till alla hus.

## Vad EnergyWizard har idag

- **Telemetri (push):** hashad hus-id, version, drivrutiner, fel *klass* + modul — aldrig feltext, logg, setpoints eller plats.
- **Flottvy (`Installationer`):** läses från samlarens `/api/stats`. Visas hos den som har `TELEMETRY_STATS_URL` (+ token) på **sin egen** installation och är inloggad som ägare.
- **Ingen** tunnel, remote shell eller live-styrning av andras hus. Flottvyn är anonym aggregatdata.

## Så ger du support (t.ex. lazgeo) flottvyn på *hans* EnergyWizard

Han ska **inte** logga in på din webb. Han kör sin egen installation och ser Installationer där.

1. Ge honom (privat) samlarens stats-URL och token, samma som på utvecklarservern:
   - URL: `https://energywizzard.profitalgos.com/telemetry/api/stats`
   - Token: värdet av `TELEMETRY_STATS_TOKEN` / samlarens `STATS_TOKEN`
2. **HA-tillägg:** under tilläggets Konfiguration fyll i
   - `telemetry_stats_url` = URL:n ovan  
   - `telemetry_stats_token` = token  
   Spara och starta om tillägget.
3. **docker-compose:** i `.env` / webdashboard-miljön:
   - `TELEMETRY_STATS_URL=…`
   - `TELEMETRY_STATS_TOKEN=…`  
   Starta om `webdashboard`.
4. Han loggar in som **ägare på sitt hus** → menyn **Installationer** (anonyma hus, felgrupper, versioner).

Han ser fortfarande sitt eget hus som vanligt. Han ser **inte** ditt hus live och kan **inte** styra andras installationer.

### Alternativ (undvik i normalfallet)

`TELEMETRY_ADMIN_USERS` på utvecklarservern + family-login där ger enbart flottvy på *din* webb (spärrad från ditt hus-UI). Det är fel modell när support redan kör EnergyWizard hemma.

## Hur vi kommer närmare FTW-admin

1. **Nu (#265):** flottvy på supportpersonens egen installation via stats-URL/token.
2. **Nästa (#227):** opt-in supportpaket (redigerad logg + control journal) som användaren bifogar.
3. **Senare:** tidsbegränsad support-grant (ägaren godkänner i UI) — samma integritetsmodell som FTW:s `support`-agent, utan Cloud-tunnel i första steget.

Styr aldrig en främmande installation utan uttryckligt ägargodkännande.
