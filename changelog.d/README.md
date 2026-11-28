# Ändringslogg utan krockar

Varje PR lägger **en egen liten fil här** i stället för att ändra `ha-addon/smartbox/CHANGELOG.md`. Då krockar inte PR:er längre på ändringsloggen (2026-11-27 krockade alla tio öppna PR:er där).

## Så skriver du ett fragment

Skapa `changelog.d/<kort-namn>.md` med en eller flera punkter, i samma stil som CHANGELOG.md:

```
- **Rubrik i fetstil (#123).** En eller två meningar om vad användaren märker, på svenska.
```

- Varje punkt börjar med `- `. Fortsätter en punkt på flera rader ska följande rader vara indragna.
- Filnamnet spelar bara roll för ordningen (alfabetiskt). Välj ett som inte kan krocka, till exempel `issue-599-ekonomi.md`.
- Rör inte `CHANGELOG.md` eller `config.yaml` i samma PR.

## Vad som händer vid släpp

När bilden för en merge är byggd slår releasejobbet (`scripts/tillagg.sh`) ihop fragmenten som fanns i den byggda commiten till nästa version överst i `CHANGELOG.md` (översta versionen + 1 i patch, dagens datum), tar bort fragmenten, taggar bilden med versionen och höjer `config.yaml`. Allt i en commit av `github-actions[bot]`. Fragment som kom in med en senare merge väntar på sin egen bild.

Gamla sättet fungerar fortfarande: ändrar en PR `CHANGELOG.md` direkt (ny rubrik överst) och inte lägger några fragment används den versionen som förut.
