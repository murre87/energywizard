"""Generisk laddar-handskakning: vilken fysisk laddare tillhör vilken bil just nu.

Husdata kan ha fler bilar än fasta laddplatser - bilarna kan byta laddplats med
varandra (t.ex. två bilar, två Easee-boxar, ingen fast koppling mellan dem).
Den här modulen generaliserar den logik som tidigare var hårdkodad för exakt
Nissan+Tesla+easee_lite+easee_carport i main.py (rad ~879-913) till godtyckligt
många bilar/laddare - SAMMA algoritm, bara parametriserad.

"Är kabeln i den här bilen?"-detekteringen (märkesspecifik - Tesla och Nissan
rapporterar det olika) stannar KVAR i main.py, en liten funktion per konfigurerad
bil - den här modulen tar bara emot redan avgjorda True/False-värden, den gissar
inget om vad som räknas som "inkopplad" för ett visst bilmärke.
"""


def resolve_charger_allocations(
    physical_chargers: dict[str, bool],
    car_plugged: dict[str, bool],
    prior_allocations: dict[str, str | None],
    default_car: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """
    physical_chargers: {fysiskt_laddar_id: ansluten_just_nu (bool)}
    car_plugged:        {bil_id: bilens kabel sitter i NÅGON av husets laddare (bool)}
    prior_allocations:  {fysiskt_laddar_id: bil_id | "guest" | None} - tillstånd från
                         förra körningen (en laddare som redan är tilldelad ändras inte).
    default_car:        {fysiskt_laddar_id: bil_id} - vilken bil husets config pekar ut
                         som "hemmahörande" på just den laddaren (house_config.yaml:s
                         evs[].charger.physical-fält). Den bilen prioriteras FÖRST för
                         just den laddaren om den har kabeln i - matchar originalets
                         beteende där easee_lite (Nissans hemmaplats) prioriterade Nissan
                         och carport (Teslas) prioriterade Tesla, inte en global ordning.

    Returnerar en uppdaterad kopia av prior_allocations. Bearbetar physical_chargers
    i dess egen (dict-)ordning - en laddare som tilldelas tidigt i samma anrop syns
    av senare laddare i samma anrop (matchar original-logikens beteende, där
    easee_lite-grenen kunde påverka vad carport-grenen såg samma varv).
    """
    default_car = default_car or {}
    allocations = dict(prior_allocations)
    for physical_id, connected in physical_chargers.items():
        if not connected or allocations.get(physical_id) is not None:
            continue
        home_car = default_car.get(physical_id)
        priority = ([home_car] if home_car else []) + [c for c in car_plugged if c != home_car]
        chosen = None
        for car_id in priority:
            if not car_plugged.get(car_id):
                continue
            # Hoppa över en bil som redan är tilldelad en ANNAN fysisk laddare
            # (samma varv eller tidigare) - en bil kan bara ladda på ett ställe.
            already_elsewhere = any(
                other_physical != physical_id and other_car == car_id
                for other_physical, other_car in allocations.items()
            )
            if already_elsewhere:
                continue
            chosen = car_id
            break
        allocations[physical_id] = chosen if chosen is not None else "guest"
    return allocations
