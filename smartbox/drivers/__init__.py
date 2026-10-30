"""Drivrutinslager för EnergyWizard Open.

Varje delsystem (bil, laddare, värmepump, sol, spa) har ett gränssnitt (ABC) här och
minst en Null-variant som gör delsystemet overksamt - "ingen enhet" är ett förstklassigt,
testat tillstånd, inte en bieffekt av defensiv kodning på andra ställen i koden.

Varje enskild sensor/funktion inom en konkret drivrutin är individuellt valfri: saknas
en entitet i husets config returnerar motsvarande fält None, aldrig ett fel. Resten av
koden (gpm.py, main.py) förväntar sig redan detta mönster via .get(key, default).

Fas 0 (scaffolding): bara gränssnitten + Null-drivrutinerna. Inga konkreta
implementationer (Easee, Tesla, Thermia/Husdata, SolarEdge, Gecko) flyttas hit förrän
Fas 1, och ingen befintlig fil kopplas till det här paketet förrän dess.
"""
