# EnergyWizard

Smart styrning av hus och elbilar (laddplan, värmepump, spabad, solel) med Home Assistant, Postgres och Tibber/Nordpool.

- `smartbox/` – styrmotorn. `smartdashboard/` – dashboarden. `ewapp/` – mobilappen (PWA) som även publicerar laddplan och lägen i Home Assistant.
- Körs med `docker-compose.yml`. Kopiera `.env.example` till `.env` och fyll i värdena. `.env` finns **inte** i git.
- Bilderna byggs av GitHub (`.github/workflows/docker.yml`) till `ghcr.io/murre87/energywizard-*` och hämtas av Watchtower.
- Home Assistant-bryggan (planen som `sensor.<bil>_laddplan`, lägen som `input_select.*`) följer avtalet i Familjetavlans `docs/SMART-LADDNING.md`.
