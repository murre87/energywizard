import asyncio
from matter_server.client import MatterClient

# --- INSTÄLLNINGAR ---
# Byt ut dessa mot de Node ID du fick när du kopplade sensorerna.
# Om du bara har en eller två sensorer, kommentera bort de rader du inte behöver.
SENSOR_MAP = {
    "matter_1": 2,  # Byt ut '2' mot Node ID för din första sensor
    "matter_2": 3,  # Byt ut '3' mot Node ID för din andra sensor
    "matter_3": 4,  # Byt ut '4' mot Node ID för din tredje sensor
}

# DEPRECATED: tidigare skrevs temperaturerna till /tmp/matter_sensors.json, men
# ingen konsument läser den filen (verifierat med grep i hela projektet). Matter-
# temperaturerna hämtas numera via Home Assistant-entiteter (homeassistant.py
# matter_1..3 / read_temperatures). Skriv-logiken är därför borttagen för att inte
# slösa I/O. Loop-beteendet (poll + sleep) bevaras oförändrat.

# Matter Server WebSocket URL
SERVER_URL = "ws://localhost:5580/ws"

# Cluster och Attribute ID för temperatur
TEMP_CLUSTER_ID = 1026  # 0x0402 TemperatureMeasurement
TEMP_ATTRIBUTE_ID = 0  # measuredValue

async def main():
    """Ansluter till Matter-servern, läser av sensorer och skriver till fil."""
    print("🤖 Startar Matter-avläsare...")
    while True:
        try:
            async with MatterClient(SERVER_URL) as client:
                print("✅ Ansluten till Matter-servern.")
                
                while True:
                    temperatures = {}
                    for name, node_id in SENSOR_MAP.items():
                        node = client.get_node(node_id)
                        if not node:
                            print(f"⚠️ Hittade inte nod {node_id} ({name}).")
                            continue

                        temp_value = None
                        # Leta efter temperatur-klustret på alla endpoints
                        for endpoint in node.endpoints.values():
                            if TEMP_CLUSTER_ID in endpoint.clusters:
                                cluster = endpoint.clusters[TEMP_CLUSTER_ID]
                                try:
                                    # Värdet är i 1/100-delar av en grad Celsius
                                    raw_value = await cluster.get_attribute_value(TEMP_ATTRIBUTE_ID)
                                    if raw_value is not None:
                                        temp_value = round(raw_value / 100.0, 1)
                                        break # Hittade temp, behöver inte leta mer på denna nod
                                except Exception as e:
                                    print(f"❌ Fel vid läsning av attribut från {name} (Node {node_id}): {e}")
                        
                        if temp_value is not None:
                            temperatures[name] = temp_value

                    # Skriv-logiken till /tmp/matter_sensors.json är borttagen (död kod –
                    # ingen läste filen). Loggar i stället avläst värde för diagnostik.
                    print(f"📈 Matter-temperaturer: {temperatures}")

                    await asyncio.sleep(60)

        except (asyncio.CancelledError, KeyboardInterrupt):
            print("🛑 Avslutar Matter-avläsare.")
            break
        except Exception as e:
            print(f"❌ Anslutning till Matter-servern misslyckades: {e}. Försöker igen om 30 sekunder...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())