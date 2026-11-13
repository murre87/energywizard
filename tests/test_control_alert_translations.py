import json
from pathlib import Path
import shutil
import subprocess

import pytest
import ev_hold
import control_alerts
from i18n_py import tr


def alerts():
    readings = [{'current_a': 11}, {'current_a': 11, 'output_limit_a': 9},
                {'current_a': 11, 'max_limit_a': 9},
                {'current_a': 11, 'reason_no_current': 'max_circuit_current_too_low'},
                {'current_a': 11, 'reason_no_current': 'unknown'}]
    return [control_alerts.build({'ev_hold': json.dumps({'tesla': ev_hold.explain(16, reading)})},
                                {'tesla': 'Tesla <42>'})[0] for reading in readings]


@pytest.mark.parametrize('language', ['en', 'cs'])
def test_actual_charging_alert_variants_translate(language):
    for alert in alerts():
        assert alert['device'] == 'Tesla <42>'
        for field in ('title', 'text', 'hint'):
            assert tr(alert[field], language) != alert[field]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node required')
def test_actual_mobile_and_dashboard_card_rendering():
    subprocess.run(['node', 'scripts/test_control_alert_translations.cjs'],
                   input=json.dumps(alerts()), text=True,
                   cwd=Path(__file__).resolve().parents[1], check=True)
