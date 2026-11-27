"""Vidarekoppling (steg 5d av uppdelningen): FTW:s Lua-värd bor nu i drivers/lua_host.py (repot energywizard-drivers).

`import lua_host` ger exakt samma modulobjekt som drivers.lua_host, så motorn, webben och testerna som läser eller ändrar `lua_host.NAMN` fungerar som förut."""
import sys

from drivers import lua_host

sys.modules[__name__] = lua_host
