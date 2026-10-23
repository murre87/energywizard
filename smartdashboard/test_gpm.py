import sys
import os
from datetime import datetime, timedelta
import pytest

# Lägg till smartbox i path så vi kan importera gpm
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'smartbox')))

from gpm import GlobalPriorityManager

def test_peak_shaving_throttles_ev_and_spa():
    """
    Testfall: Vad händer om Nissan Leaf och Tesla drar mycket ström, 
    och vi är farligt nära effekttaket?
    Förväntat resultat: GPM (Prio 10) ska nolla båda bilarna och sätta Spa i Eco.
    """
    engine = GlobalPriorityManager()
    
    # Simulera en tidpunkt i slutet av timmen (45 minuter in)
    mock_now = datetime(2023, 10, 24, 18, 45, 0)
    
    mock_state = {
        'now': mock_now,
        'current_price': 1.50,
        'peak_shaving_enabled': True,
        'current_target_limit': 10.0,      # Vi har 10 kW som smärtgräns
        'consumed_kwh_this_hour': 9.5,     # Vi har redan förbrukat 9.5 kWh denna timme!
        'predicted_base_load_kw': 2.0,     # Huset kommer dra ca 2 kW i snitt
        'nissan_soc': 50,
        'nissan_connected': True,
        'tesla_soc': 50,
        'tesla_connected': True,
        'nissan_phases': 'SinglePhase',
        'tesla_phases': 'ThreePhase',
        'indoor_temp': 21.0,               # Inget akut frys-läge
        'indoor_min': 19.0,
        'spa_temp': 38.0,
    }
    
    # Kör GPM-motorn
    actions = engine.evaluate(mock_state)
    
    # 1. Kontrollera att bilarna stängdes av
    assert actions['nissan_limit_a'] == 0, "Nissan strömbegränsning ska vara 0 A vid Peak Shaving larm"
    assert actions['tesla_limit_a'] == 0, "Tesla strömbegränsning ska vara 0 A vid Peak Shaving larm"
    
    # 2. Kontrollera att spabadet sattes i viloläge
    assert actions['spa_eco'] is True, "Spabadet ska tvingas till Eco Mode"
    
    # 3. Kontrollera loggen för att se att Prio 10 faktiskt triggades
    log_messages = "\n".join(actions['log'])
    assert "Prio 10 (PEAK)" in log_messages, "GPM loggade inte att Peak Shaving aktiverades"
