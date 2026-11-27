"""Kallt inne räknas först efter 30 min i följd (2026-11-06: en vädring gav 14,6 °C i några minuter, motorn
aviserade och tvingade värmen på oavsett elpris direkt)."""
from datetime import datetime, timedelta

import pytest

from gpm import GlobalPriorityManager
from sustained import COLD_CONFIRM_MIN, Sustained

T0 = datetime(2026, 11, 6, 9, 17)


def test_vadring_ger_ingen_bekraftelse_men_30_min_kyla_gor():
    w = Sustained()
    temps = [21.8, 19.6, 17.8, 16.2, 15.2, 14.6, 15.9, 17.9, 19.3, 20.4]          # som 09:16-09:33 (varannan minut)
    assert not any(w.update(t < 18.0, T0 + timedelta(minutes=2 * i)) for i, t in enumerate(temps))
    w = Sustained()
    out = [w.update(True, T0 + timedelta(minutes=m)) for m in range(0, COLD_CONFIRM_MIN + 1)]
    assert out[-1] is True and not any(out[:-1])
    assert w.update(False, T0 + timedelta(minutes=31)) is False and w.since is None


def _cold_actions(confirmed):
    st = {"now": datetime(2026, 11, 6, 9, 21), "car_ids": [], "indoor_temp": 15.2, "indoor_min": 19.0,
          "outdoor_avg_5d": 2.0, "price": 3.6}
    if confirmed is not None:
        st["indoor_cold_confirmed"] = confirmed
    return GlobalPriorityManager().evaluate(st)


@pytest.mark.no_planner_input_guard            # äldre testnyckel (price) i minimal indata: testar kylvakten, inte kontraktet
def test_gpm_tvingar_inte_varme_forran_kylan_bekraftats():
    assert not any("Kallt inne" in l for l in _cold_actions(False)["log"])
    assert any("Kallt inne" in l for l in _cold_actions(True)["log"])
    assert any("Kallt inne" in l for l in _cold_actions(None)["log"])     # utan nyckeln: som förut (återuppspelning)
