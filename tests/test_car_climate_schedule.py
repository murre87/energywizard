"""#233: klockslag och temperatur för kupévärmen, innan de sparas."""
import pytest

import car_climate_schedule as cc


def test_normaliserar_tid_och_temperatur():
    assert cc.normalize(True, "07:30", 21) == {"enabled": True, "time": "07:30", "temp": 21.0}
    assert cc.normalize("ja", "07:30:00", "19.5")["temp"] == 19.5
    assert cc.normalize("false", "06:00", 21)["enabled"] is False
    assert cc.normalize(None, None, None) == {"enabled": False, "time": "07:00", "temp": 21.0}


@pytest.mark.parametrize("time_s", ["24:00", "7:00", "07-00", "ab:cd", ""])
def test_avvisar_ogiltig_tid(time_s):
    with pytest.raises(ValueError, match="Ogiltig tid"):
        cc.normalize(True, time_s, 21)


@pytest.mark.parametrize("temp", [14.9, 28.1, "nan"])
def test_avvisar_temperatur_utanfor_15_28(temp):
    with pytest.raises(ValueError, match="15 och 28"):
        cc.normalize(True, "07:00", temp)


def test_avvisar_temperatur_som_inte_ar_ett_tal():
    with pytest.raises(ValueError, match="Ogiltig temperatur"):
        cc.normalize(True, "07:00", "kallt")


def test_vy_visar_om_bilen_har_klimat():
    row = {"enabled": True, "target_time": "06:45", "target_temp": 20}
    assert cc.view(row, True) == {"enabled": True, "time": "06:45", "temp": 20.0, "has_climate": True}
    assert cc.view(None, False)["has_climate"] is False
