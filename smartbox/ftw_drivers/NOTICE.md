# FTW-drivrutiner / FTW drivers

**Svenska.** Lua-drivrutinerna här (93 st) kommer från [srcfl/device-drivers](https://github.com/srcfl/device-drivers),
Copyright 2026 Sourceful Labs AB and contributors, commit
[`e07d27038e83`](https://github.com/srcfl/device-drivers/tree/e07d27038e83e431cc01c1cd988ffcb1997355c0) (hämtade
2026-11-05). De används och sprids enligt upstreams licens: **GNU AGPL-3.0 only**, med de villkor och notiser som står i
upstreams filer, som följer med här oförändrade:

- [`UPSTREAM-LICENSE`](UPSTREAM-LICENSE) – licenstexten (AGPL-3.0 med Energyplan-undantaget)
- [`UPSTREAM-NOTICE`](UPSTREAM-NOTICE) – upphovsrätt och tidigare Apache-rättigheter
- [`UPSTREAM-LICENSING.md`](UPSTREAM-LICENSING.md) – upstreams förklaring av licensen
- [`UPSTREAM-THIRD_PARTY_NOTICES.md`](UPSTREAM-THIRD_PARTY_NOTICES.md) – tredjepartsfiler med egna licenser

Inget separat tillstånd från Sourceful finns eller behövs utöver licensen. (En tidigare version av den här filen
påstod att Sourceful gett sitt OK. Det var en övertolkning av ett vänligt svar på Facebook och är struket, se #231.)

**Ändringar mot upstream** (allt annat är oförändrat):

| Fil | Datum | Ändring | Commit |
|---|---|---|---|
| `deye-svk.lua` | 2026-11-09 | Skydd mot nil-SoC vid misslyckad poll i energiheadroom-beräkningen (samma skydd som i `50-125k-svk*.lua`). Av lazgeo, #215. Skickad till källan: [srcfl/device-drivers#224](https://github.com/srcfl/device-drivers/pull/224). | `101713e` |
| `deye-svk.lua` | 2026-11-12 | `read_rated_w` och `detect_hv` indexerar inte en nil-tabell när Modbus svarar `(nil, fel)` utan att kasta. Det gav `LuaError` i `driver_poll` varje varv tills märkeffekten var känd (#297). | |

Drivrutinerna körs av `smartbox/lua_host.py` och används via `smartbox/drivers/ftw_device.py` (`driver: ftw` för
batteri och solceller i house_config.yaml). Styrning (laddning, urladdning, exportbegränsning) är avstängd för alla
drivrutiner som inte finns i `FTW_CONTROL_VERIFIED` i ftw_device.py, om inte installationen uttryckligen sätter
`control_unverified: true`. Läsning fungerar för alla.

Rättningar och förbättringar av drivrutinerna skickas i första hand till källan,
[srcfl/device-drivers](https://github.com/srcfl/device-drivers), och nya versioner hämtas därifrån.

**English.** The Lua drivers here (93) come from [srcfl/device-drivers](https://github.com/srcfl/device-drivers),
Copyright 2026 Sourceful Labs AB and contributors, commit `e07d27038e83` (fetched 2026-11-05). They are used and
distributed under the upstream license, **GNU AGPL-3.0 only**, with the terms and notices in the upstream files that
are included here unchanged (`UPSTREAM-LICENSE`, `UPSTREAM-NOTICE`, `UPSTREAM-LICENSING.md`,
`UPSTREAM-THIRD_PARTY_NOTICES.md`). No separate permission from Sourceful exists or is claimed beyond the license.
Changes from upstream are listed in the table above (`deye-svk.lua`: nil-SoC guard #215, and the #297 guard so a failed Modbus read does not crash `driver_poll`), and fixes
are sent upstream as pull requests.
