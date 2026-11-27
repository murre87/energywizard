"""Vidarekoppling (steg 5d av uppdelningen): Thermia/Husdata-värmepumpen bor nu i drivers/thermia_pump.py (repot energywizard-drivers).

`import pump` ger exakt samma modulobjekt som drivers.thermia_pump, så motorn, webben och testerna som läser eller ändrar `pump.NAMN` fungerar som förut."""
import sys

from drivers import thermia_pump

sys.modules[__name__] = thermia_pump
