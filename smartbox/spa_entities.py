"""Vidarekoppling (steg 5d av uppdelningen): Gecko-spabadets entiteter bor nu i drivers/spa_entities.py (repot energywizard-drivers).

`import spa_entities` ger exakt samma modulobjekt som drivers.spa_entities, så motorn, webben och testerna som läser eller ändrar `spa_entities.NAMN` fungerar som förut."""
import sys

from drivers import spa_entities

sys.modules[__name__] = spa_entities
