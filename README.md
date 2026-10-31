# EnergyWizard Open

Smart styrning av hus och elbilar efter elpriset — värmepump, elbilsladdning, solel
och spabad, byggt på Home Assistant, Postgres och Tibber/Nordpool. Öppen källkod,
inget abonnemang. Se [energywizard-sidan](https://murre87.github.io/energywizard/)
för riktiga besparingssiffror och en kunskapsbank om hur styrningen fungerar.

**Status:** huvudstyrloopen (`smartbox/`) går sedan nyligen via en drivrutins-
arkitektur (`smartbox/drivers/`, se `smartbox/house_config.py`) istället för
hårdkodat mot ett specifikt hus. Det gör det genuint möjligt för andra att koppla
in sin egen hårdvara - men bara för de märken som redan har en drivrutin (se
nedan). Fler märken är ett väntat, naturligt sätt att bidra.

## Komma igång

1. Klona repot och kopiera `.env.example` till `.env` - fyll i dina egna värden
   (Home Assistant-IP/token, Postgres-lösenord osv). `.env` checkas aldrig in.
2. Kopiera `config/house_config.example.yaml` till en egen fil (t.ex.
   `config/house_config.yaml`) och fyll i det du faktiskt har - en helt tom fil
   (bara `house_id`) är ett giltigt, testat utgångsläge där alla delsystem bara
   blir overksamma istället för att krascha. Varje enskild entitet är också
   individuellt valfri.
3. Peka `HOUSE_CONFIG_HOST_PATH` i din `.env` mot den filen (standard är annars
   `config/examples/emil_house.yaml`, som är mitt eget hus - bra som referens för
   hur en riktig, ifylld config ser ut).
4. `docker compose up -d` - `smartbox` är huvudmotorn. `webdashboard` (dator/
   surfplatta) och `ewapp` (mobil, PWA) är separata profiler:
   `docker compose --profile webdashboard up -d webdashboard`.
5. Valfritt, avancerat: kör EnergyWizard under samma adress som din egna Home
   Assistant (för Container-installationer utan Supervisor) - se
   [kunskapsbanksartikeln](https://murre87.github.io/energywizard/kunskapsbank/ha-gateway.html).

## Vilka märken stöds idag

Drivrutinsarkitekturen (`smartbox/drivers/`) är byggd för att vara
märkesoberoende, men konkreta drivrutiner finns bara för det som redan testats
mot riktig hårdvara:

| Delsystem    | Stödda märken idag           |
|--------------|-------------------------------|
| Värmepump    | Thermia/Husdata (Modbus)      |
| Elbil        | Nissan, Tesla, + en generisk (läser valfri HA-entitet, funkar för de flesta bilar) |
| Laddare      | Easee                         |
| Solceller    | SolarEdge                     |
| Spabad       | Gecko                         |

Saknas ditt märke? Den generiska elbils-drivrutinen (`generic_ev`) funkar redan
för praktiskt taget vilken bil som helst som har SOC/laddstatus i Home Assistant.
För övriga delsystem - se `smartbox/drivers/*.py` för gränssnitten och skicka
gärna ett bidrag.

Se [ROADMAP.md](ROADMAP.md) för vad som är nästa rimliga steg och varför.

## Struktur

- `smartbox/` – styrmotorn (huvudloopen, drivrutinerna, prioritetsmotorn).
- `webdashboard/` – ny dator-/surfplatte-dashboard. `ewapp/` – mobilappen (PWA).
- `smartdashboard/` – äldre Streamlit-dashboard, fasas ut.
- `docs/` – den publika sidan (GitHub Pages).
- Bilderna byggs av GitHub (`.github/workflows/docker.yml`) till
  `ghcr.io/murre87/energywizard-*` och hämtas automatiskt av Watchtower.
