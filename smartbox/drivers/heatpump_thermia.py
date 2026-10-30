"""ThermiaHusdataHeatPumpDriver: tunt omslag kring pump.py (Thermia Diplomat Optimum G3
via en Husdata H66 Modbus-gateway). Register-karta, skalningsfaktorer och gateway-kvirkar
rörs inte - de ligger kvar i pump.py precis som idag, bara nådda via gränssnittet här.

set_operating_mode tar - för nu - samma råa heltalskoder som pump.set_operating_mode alltid
tagit (main.py anropar den så idag). En riktig normaliserad enum-mappning (string -> kod)
är ett medvetet senare steg (Fas 5, när ett andra värmepumpsmärke faktiskt behöver en
annan mappning att jämföra mot) - att gissa en mappning nu utan att verifiera den mot en
riktig andra implementation hade varit att införa en bugg, inte ta bort en."""
import pump
from drivers.heatpump import HeatPumpDriver


class ThermiaHusdataHeatPumpDriver(HeatPumpDriver):
    def read_sensors(self) -> dict:
        return pump.read_sensors() or {}

    def set_room_temp(self, target_c: float) -> bool:
        return bool(pump.set_room_temp(target_c))

    def set_water_stop_temp(self, target_c: float) -> bool:
        return bool(pump.set_water_stop_temp(target_c))

    def set_water_start_temp(self, target_c: float) -> bool:
        return bool(pump.set_water_start_temp(target_c))

    def set_heating_start_temp(self, target_c: float) -> bool:
        return bool(pump.set_heating_start_temp(target_c))

    def set_operating_mode(self, mode) -> bool:
        return bool(pump.set_operating_mode(mode))
