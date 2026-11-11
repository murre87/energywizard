"""Regression cases for OTE, Czech VAT and optional HDO distribution."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import distribution_tariff as D
import ew_settings
import nordpool as N
from price_options import extended_price_options, validate_result


class CzechTariffs(unittest.TestCase):
    def setUp(self):
        self.settings = {"price_country": "CZ"}
        self.patches = [patch.object(ew_settings, "get", side_effect=lambda k, d=None: self.settings.get(k, d)),
                        patch.dict("os.environ", {}, clear=True)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        D._CACHE.clear()

    def test_czech_defaults(self):
        c = N.cost_settings()
        self.assertEqual((c["area"], c["currency"], c["symbol"], c["vat_pct"]), ("CZ", "CZK", "Kč", 21))
        self.assertFalse(N.prices_include_vat())
        self.assertAlmostEqual(N.full_buy_cost(2), 2.42)

    def test_vat_already_in_sensor(self):
        self.settings["price_includes_vat"] = True
        self.assertAlmostEqual(N.full_buy_cost(2.42), 2.42)
        self.assertAlmostEqual(N.full_sell_income(2.42), 2)

    def test_vat_override(self):
        self.settings["price_vat_pct"] = 0
        self.assertEqual(N.full_buy_cost(2), 2)

    def test_swedish_defaults_unchanged(self):
        self.settings.clear()
        self.assertAlmostEqual(N.full_buy_cost(1), 1.87675)
        self.assertAlmostEqual(N.full_sell_income(1), 1.02125)

    def test_hdo_inactive_outside_czechia(self):
        self.settings.update(price_country="SE", price_hdo_entity="sensor.cez_hdo_schedule_home",
                             price_distribution_nt=.2, price_distribution_vt=1.2)
        with patch.object(D, "schedule_for", side_effect=AssertionError("HDO must not be fetched")):
            self.assertEqual(D.distribution_at(None, N.cost_settings()), 0)
            self.assertEqual(D.sql_distribution_expr("t", N.cost_settings()), "")
            self.assertAlmostEqual(N.full_buy_cost(1), 1.87675)

    def test_fixed_buy_independent_of_spot(self):
        self.settings.update(price_buy_mode="fixed", price_buy_fixed=3, price_buy_extra=.1, price_sell_extra=-.3)
        for p in (-5, 0, 12):
            self.assertAlmostEqual(N.full_buy_cost(p), 3.1)
            self.assertAlmostEqual(N.full_sell_income(p), p - .3)
            self.assertAlmostEqual(eval(N.sql_buy_cost_expr("p")), 3.1)

    def test_planning_price_uses_contract_and_hdo(self):
        now = datetime.fromisoformat("2026-11-10T07:00:00+01:00")
        self.settings.update(price_buy_mode="fixed", price_buy_fixed=3, price_buy_extra=.1)
        self.assertAlmostEqual(N.planning_buy_price(-5, now), N.planning_buy_price(10, now))
        rows = self.hdo()
        self.settings.update(price_buy_mode="hdo", price_buy_nt=2, price_buy_vt=4)
        with patch.object(D, "schedule_for", return_value=rows):
            cheap = N.planning_buy_price(100, now)
            expensive = N.planning_buy_price(-100, now.replace(hour=9))
            self.assertLess(cheap, expensive)
            self.assertAlmostEqual(cheap, (2 - .1) / 1.21)

    def test_partial_updates_preserve_valid_contract(self):
        current = {"country": "CZ", "buy_mode": "fixed", "buy_fixed": 3,
                   "sell_mode": "spot", "hdo_entity": ""}
        with self.assertRaises(ValueError):
            validate_result(current, {"price_buy_fixed": None})
        validate_result(current, {"price_buy_fixed": 0})
        current.update(buy_mode="hdo", hdo_entity="sensor.hdo", buy_nt=2, buy_vt=4)
        with self.assertRaises(ValueError):
            validate_result(current, {"price_hdo_entity": None})
        with self.assertRaises(ValueError):
            validate_result(current, {"price_buy_nt": None})

    def test_fixed_sell_is_final_contract_price(self):
        self.settings.update(price_sell_mode="fixed", price_sell_fixed=1.5, price_sell_extra=-.1)
        self.assertAlmostEqual(N.full_sell_income(-20), 1.4)
        self.assertAlmostEqual(eval(N.sql_sell_income_expr("p")), 1.4)

    def test_python_sql_parity(self):
        for vat in (False, True):
            self.settings.update(price_includes_vat=vat, price_buy_extra=.2, price_sell_extra=-.3)
            for p in (-3, 0, 8):
                self.assertAlmostEqual(eval(N.sql_buy_cost_expr("p")), N.full_buy_cost(p))
                self.assertAlmostEqual(eval(N.sql_sell_income_expr("p")), N.full_sell_income(p))

    def test_actual_ote_top_level_attributes(self):
        attrs = {"friendly_name": "Spot", "unit_of_measurement": "Kč/MWh",
                 "2026-11-10T00:00:00+01:00": -200, "2026-11-10T00:15:00+01:00": 1500}
        rows = N.parse_price_attributes(attrs, attrs["unit_of_measurement"])
        self.assertEqual([r[2] for r in rows], [-.2, 1.5])
        self.assertEqual((rows[0][1] - rows[0][0]).total_seconds(), 900)
        self.assertEqual(N.recognize_price_entity({"entity_id": "sensor.current_spot_electricity_price", "attributes": attrs}), "OTE (CZ)")

    def test_ote_dst_days(self):
        from datetime import timedelta
        # UTC instants prevent duplicated autumn local hours from collapsing.
        for length in (92, 96, 100):
            start = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
            attrs = {(start + timedelta(minutes=15*i)).isoformat(): i/100 for i in range(length)}
            rows = N.parse_price_attributes(attrs, "CZK/kWh")
            self.assertEqual(len(rows), length)
            self.assertTrue(all((e-s).total_seconds() == 900 for s,e,p in rows))

    def hdo(self):
        self.settings.update(price_hdo_entity="sensor.cez_hdo_schedule_home", price_distribution_nt=.2, price_distribution_vt=1.2)
        return D.parse_schedule({"schedule": [
            {"start": "2026-11-10T00:00:00+01:00", "end": "2026-11-10T08:00:00+01:00", "tariff": "NT"},
            {"start": "2026-11-10T08:00:00+01:00", "end": "2026-11-10T23:59:59+01:00", "tariff": "VT"}]})

    def test_hdo_boundaries_and_fallback(self):
        rows = self.hdo()
        with patch.object(D, "schedule_for", return_value=rows):
            for iso, extra in (("2026-11-10T07:59:59+01:00", .2), ("2026-11-10T08:00:00+01:00", 1.2),
                               ("2026-11-10T23:59:59+01:00", 1.2), ("2026-11-11T01:00:00+01:00", 1.2)):
                self.assertAlmostEqual(N.full_buy_cost(1, datetime.fromisoformat(iso)), 1.21+extra)
            self.assertEqual(N.full_sell_income(1), 1)
            expr = N.sql_buy_cost_expr("p", "time_start")
            self.assertIn("TIMESTAMPTZ '2026-11-10T07:00:00+00:00'", expr)
            self.assertIn("ELSE 1.2 END", expr)

    def test_hdo_no_data_uses_higher_rate(self):
        self.hdo()
        self.settings.update(price_distribution_nt=2, price_distribution_vt=1)
        with patch.object(D, "schedule_for", return_value=[]):
            self.assertAlmostEqual(N.full_buy_cost(1), 3.21)
            self.assertIn("+ 2.0", N.sql_buy_cost_expr("p", "time_start"))

    def test_schedule_rejects_overlap(self):
        rows = [{"start": "2026-11-10T00:00:00", "end": "2026-11-10T08:00:00", "tariff": "NT"},
                {"start": "2026-11-10T07:00:00", "end": "2026-11-10T09:00:00", "tariff": "VT"}]
        self.assertEqual(D.parse_schedule({"schedule": rows}), [])

    def test_hdo_fetch_cache_and_failure(self):
        from types import SimpleNamespace
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"state": "10.11.2026", "attributes": {"schedule": []}})
        fake = SimpleNamespace(_BASE="http://ha/api", _HEADERS={}, _VERIFY=True,
                               requests=SimpleNamespace(get=lambda *a, **k: response))
        with patch.dict("sys.modules", {"homeassistant": fake}), patch.object(fake.requests, "get", return_value=response) as get:
            D.schedule_for("sensor.hdo")
            D.schedule_for("sensor.hdo")
            self.assertEqual(get.call_count, 1)
            D._CACHE.clear()
            get.side_effect = OSError("offline")
            self.assertEqual(D.schedule_for("sensor.hdo"), [])

    def test_blank_fields_never_become_zero(self):
        self.assertIsNone(N.cost_settings()["buy_fixed"])
        self.assertEqual(extended_price_options({"buy_mode": "spot", "buy_fixed": ""}), {"price_buy_mode": "spot", "price_buy_fixed": None})
        for body in ({"buy_mode": "fixed", "buy_fixed": ""}, {"sell_mode": "fixed"},
                     {"hdo_entity": "sensor.hdo", "distribution_nt": "", "distribution_vt": 1}):
            with self.assertRaises(ValueError):
                extended_price_options(body)
        self.assertEqual(extended_price_options({"buy_mode": "fixed", "buy_fixed": 0})["price_buy_fixed"], 0)

    def test_final_hdo_purchase_avoids_double_fees_and_vat(self):
        rows = self.hdo()
        self.settings.update(price_buy_mode="hdo", price_buy_nt=3.2, price_buy_vt=6.1,
                             price_buy_extra=4, price_tou_extra=5, price_includes_vat=False)
        with patch.object(D, "schedule_for", return_value=rows):
            for iso, expected in (("2026-11-10T07:59:59+01:00", 3.2), ("2026-11-10T08:00:00+01:00", 6.1)):
                for spot in (-10, 1, 50):
                    self.assertEqual(N.full_buy_cost(spot, datetime.fromisoformat(iso)), expected)
            self.assertEqual(N.full_sell_income(2), 2)
            expr = N.sql_buy_cost_expr("p", "t")
            self.assertIn("THEN 3.2", expr)
            self.assertIn("ELSE 6.1 END", expr)
            self.assertNotIn("* 1.21", expr)
            self.assertNotIn(" + 4", expr)

    def test_final_hdo_purchase_missing_schedule_uses_higher_price(self):
        self.settings.update(price_buy_mode="hdo", price_hdo_entity="sensor.hdo", price_buy_nt=6, price_buy_vt=3)
        with patch.object(D, "schedule_for", return_value=[]):
            self.assertEqual(N.full_buy_cost(-5), 6)
            self.assertEqual(eval(N.sql_buy_cost_expr("p", "t")), 6)

    def test_hdo_live_prices_and_saved_outage_fallback(self):
        self.settings.update(price_buy_mode="hdo", price_hdo_price_source="ha", price_hdo_entity="sensor.hdo", price_buy_nt=3, price_buy_vt=6)
        with patch.object(D, "prices_for", return_value=(4, 7)), patch.object(D, "schedule_for", return_value=[]):
            self.assertEqual(N.full_buy_cost(1), 7)
            self.assertEqual(eval(N.sql_buy_cost_expr("p", "t")), 7)
        with patch.object(D, "prices_for", return_value=None), patch.object(D, "schedule_for", return_value=[]):
            self.assertEqual(N.full_buy_cost(1), 6)

    def test_hdo_prices_use_both_attributes_not_current_state(self):
        from types import SimpleNamespace
        attrs = {"low_tariff_price": 3.2, "high_tariff_price": 6.1, "schedule": []}
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"state": "99", "attributes": attrs})
        fake = SimpleNamespace(_BASE="http://ha/api", _HEADERS={}, _VERIFY=True,
                               requests=SimpleNamespace(get=lambda *a, **k: response))
        with patch.dict("sys.modules", {"homeassistant": fake}):
            self.assertEqual(D.prices_for("sensor.hdo"), (3.2, 6.1))
            for values in ((0, 0), (True, 3), (3, float("nan")), (None, 5)):
                D._CACHE.clear()
                attrs.update(low_tariff_price=values[0], high_tariff_price=values[1])
                self.assertIsNone(D.prices_for("sensor.hdo"))

    def test_hdo_purchase_validation(self):
        valid = {"country": "CZ", "buy_mode": "hdo", "hdo_entity": "sensor.hdo", "buy_nt": "3,2", "buy_vt": 6}
        self.assertEqual(extended_price_options(valid)["price_buy_nt"], 3.2)
        self.assertEqual(extended_price_options({**valid, "hdo_price_source": "ha", "buy_nt": "", "buy_vt": ""})["price_hdo_price_source"], "ha")
        for change in ({"country": "SE"}, {"hdo_entity": ""}, {"buy_nt": ""}, {"buy_vt": "nan"},
                       {"hdo_price_source": "unknown"}, {"sell_mode": "hdo"}):
            with self.assertRaises(ValueError):
                extended_price_options({**valid, **change})

    def test_leaving_czech_hdo_preserves_other_country_settings(self):
        body = {"country": "SE", "buy_mode": "spot", "hdo_entity": "sensor.hdo", "distribution_nt": "", "distribution_vt": ""}
        self.assertEqual(extended_price_options(body)["price_buy_mode"], "spot")

    def test_input_validation(self):
        for body in ({"distribution_nt": "nan"}, {"distribution_vt": -1}, {"buy_fixed": "inf"},
                     {"buy_mode": "oops"}, {"hdo_entity": "sensor.x'"}):
            with self.assertRaises(ValueError):
                extended_price_options(body)
        self.assertEqual(extended_price_options({}), {})
        self.assertEqual(extended_price_options({"distribution_nt": "0,25"}), {"price_distribution_nt": .25})


if __name__ == "__main__":
    unittest.main()
