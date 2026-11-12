"""#250: DiskFull under log_status ska vara varning, inte programfel (❌)."""
from unittest.mock import patch

import logger


def test_log_status_diskfull_warns(capsys):
    class DiskFull(Exception):
        sqlstate = "53100"

    DiskFull.__name__ = "DiskFull"
    with patch("logger.get_db", side_effect=DiskFull("no space")):
        logger.log_status(
            price=1.0, indoor=20, water=40, target_room=21, water_mode=0,
            forward=30, retur=25, calc_forward=30, outdoor=5,
            avg_l1=0, avg_l2=0, avg_l3=0, avg_tot=0,
            consumed_kwh=0, total_kwh=0,
            cloud_cover=0, wind_speed=0, net_power=0, wind_dir=0,
            solar_forecast_w=0, pump={},
        )
    out = capsys.readouterr().out
    assert "⚠️" in out and "Disk" in out
    assert "❌" not in out
