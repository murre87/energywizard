"""Utökat facit för gpm (steg 4a av uppdelningen): scenarier som täcker de nycklar de 2 600 ursprungliga scenarierna aldrig ger planeringen,
nämligen värmeåterkoppling, bortaläge, varmvattnets ML, spaextra och elbilens laddtak (34 av de 75 nycklar gpm läser).

Basen är samma scenarier som tests/gpm_golden_gen.py; ovanpå läggs de saknade nycklarna med värden som liknar det main.py skickar.
Facit (tests/fixtures/gpm_golden_ext.json.gz) skapades med koden som den var när täckningen lades till, och fångar beteendet så som det är
i dag, inte nödvändigtvis som det borde vara: det är skyddsnätet för uppdelningen, och en avsiktlig ändring regenereras med
python tests/gpm_ext_gen.py > /tmp/gpm_ext.json && gzip -c /tmp/gpm_ext.json > tests/fixtures/gpm_golden_ext.json.gz"""
import json
import os
import random
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
sys.path.insert(0, os.path.dirname(__file__))
import gpm_golden_gen as base

SEED, N, STEPS = 4711, 260, 8


def scenarios(seed=SEED, n=N, steps=STEPS):
    rnd = random.Random(seed)
    out = []
    for seq in base.scenarios(seed=seed, n=n, steps=steps):
        fixed = {
            "heat_feedback": rnd.choice([None, "av", "skugga", "på", "på", "på"]),
            "heat_feedback_boost": rnd.choice([1.0, 0.5, 2.0]),
            "heat_feedback_min_sp": rnd.choice([None, 16.0, 18.5, 19.5]),
            "heat_feedback_max_sp": rnd.choice([None, 21.5, 23.0, 25.0]),
            "heat_aux_guard_dm": rnd.choice([None, -200.0, -300.0]),
            "heat_ml_w": rnd.choice([None, [0.05, 0.03, -0.02, -0.004], [0.0, 0.05, -0.04, -0.006]]),
            "heat_ml_bias": rnd.choice([0.0, 0.1, -0.05]),
            "hw_ml": rnd.choice([None, "av", "skugga", "på"]),
            "hw_profile": rnd.choice([None, {(d, h): 0.7 for d in range(7) for h in (6, 7, 18, 19, 20)}, {(d, 7): 0.9 for d in range(7)}]),
            "has_spa": rnd.random() < 0.8,
            "spa_force_eco": rnd.random() < 0.15,
            "spa_force_heat": rnd.random() < 0.15,
            "spa_target_scheduled": rnd.choice([None, 36.0, 38.5]),
            "spa_bath_note": rnd.choice([None, "Bad kl 19", "Badtid saknas"]),
            "solar_order": rnd.choice([None, None, ["ev", "spa", "hotwater", "house", "battery"], ["spa", "ev", "battery", "house", "hotwater"]]),
            "heat_cap_sp": rnd.choice([None, 21.0, 22.5]),
            "away_mode_active": rnd.random() < 0.15,
        }
        new = []
        for st in seq:
            st = dict(st)
            st.update(fixed)
            temp = st.get("indoor_temp", 21.0)
            st.update({
                "indoor_low2": rnd.choice([None, round(temp - rnd.uniform(0.0, 1.8), 2)]),
                "indoor_cold_confirmed": rnd.random() < 0.1,
                "degree_minutes": rnd.choice([None, 0.0, -100.0, -350.0]),
                "forward_temp": rnd.choice([None, 31.0, 38.0, 45.0]),
                "calc_forward_temp": rnd.choice([None, 33.0, 40.0]),
                "pump_setpoint": rnd.choice([None, 20.0, 22.0]),
                "brine_out_temp": rnd.choice([None, 2.0, -3.0, -8.0]),
                "predicted_cooling_rate": rnd.choice([0.0, 0.1, 0.4, -0.2]),     # main skickar alltid ett tal (learning.predict_house_cooling_rate)
                "heat_horizon": rnd.choice([None, (None, None), (0.5, 3.0), (2.0, 4.0), (6.0, 2.0)]),
                "all_prices_tou": rnd.choice([None, [round(rnd.uniform(0.2, 2.5), 3) for _ in range(24)]]),
                "away_recovering": fixed["away_mode_active"] and rnd.random() < 0.4,
                "hw_probability": rnd.choice([0.1, 0.3, 0.6, 0.9]),
                "spa_measured_w": rnd.choice([None, 2800.0, 3300.0]),
                "spa_should_heat_now": rnd.random() < 0.3,
                "spa_target_scheduled_active": fixed["spa_target_scheduled"] is not None and rnd.random() < 0.5,      # main skickar dem ihop
                "ev_load_cap_a": rnd.choice([None, 10, 16, 25]),
            })
            new.append(st)
        out.append(new)
    return out


def run():
    import gpm
    res = []
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), \
            patch("gpm.notifier"), patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        for seq in scenarios():
            eng = gpm.GlobalPriorityManager()
            res.append([base._clean(dict(eng.evaluate(dict(st)))) for st in seq])
    return res


if __name__ == "__main__":
    json.dump(run(), sys.stdout, ensure_ascii=False)
