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
- **Flottvy (`Installationer`):** på utvecklarservern (`TELEMETRY_STATS_URL`). Owner ser den plus sitt hus. Namn i `TELEMETRY_ADMIN_USERS` (#265), t.ex. `lazgeo` som `family`, ser **bara** Installationer — inte ägarens Översikt/Elbil/logg (UI + API-spärr).
- **Ingen** tunnel, remote shell eller live-styrning av andras hus.

## Hur vi kommer närmare FTW-admin

1. **Nu (#265):** fler personer får samma *anonyma* flott-/felvy som Emil.
2. **Nästa (#227):** opt-in supportpaket (redigerad logg + control journal-sammanfattning) som användaren bifogar till auto-issue eller skickar manuellt.
3. **Senare:** tidsbegränsad support-grant (ägaren godkänner i UI) som tillfälligt laddar upp mer diagnostik — samma integritetsmodell som FTW:s `support`-agent, utan Cloud-tunnel i första steget.

Styr aldrig en främmande installation utan uttryckligt ägargodkännande.
