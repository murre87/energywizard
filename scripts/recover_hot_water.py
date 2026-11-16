"""Recover EW's journal after operator reconciliation; never sends heater commands."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'smartbox'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--journal', required=True, type=Path)
    parser.add_argument('--confirm-exclusive-ownership', action='store_true')
    parser.add_argument('--confirm-pending-commands-settled', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_exclusive_ownership or not args.confirm_pending_commands_settled:
        parser.error('Stop EW and other writers, settle pending commands and explicitly confirm both conditions')
    try:
        import yaml
        from drivers.heatpump_nibe_local import NibeLocalHeatPumpDriver
        from hot_water_recovery import recover_released
        with args.config.open(encoding='utf-8') as source:
            house = yaml.safe_load(source)
        hp = house['heat_pump']
        driver = NibeLocalHeatPumpDriver(connection=hp.get('connection'), points=hp.get('points'),
                                         control_enabled=False)
        result = recover_released(args.journal, house, driver, now=time.time(),
            exclusive_owner_confirmed=True, pending_commands_settled=True)
    except Exception:
        parser.error('Recovery blocked; check the journal, configuration, process lock and local released readback')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
