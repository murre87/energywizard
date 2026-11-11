"""Exercise Czech tariff arithmetic against PostgreSQL and real HA-shaped inputs."""
from datetime import datetime, timezone, timedelta

import pytest
import distribution_tariff as hdo
import ew_settings
import nordpool


@pytest.mark.parametrize('mode', ['spot', 'fixed', 'hdo'])
def test_czech_python_and_postgres_match_on_hdo_boundaries(db, monkeypatch, mode):
    values = {'price_country':'CZ', 'price_ha_entity':'sensor.ote', 'price_includes_vat':False,
              'price_buy_mode':mode, 'price_buy_fixed':3.0, 'price_buy_nt':2.0, 'price_buy_vt':4.0,
              'price_hdo_entity':'sensor.hdo', 'price_distribution_nt':.25, 'price_distribution_vt':1.2,
              'price_buy_extra':.3}
    monkeypatch.setattr(ew_settings, 'get', lambda k, default=None: values.get(k, default))
    rows = hdo.parse_schedule({'schedule':[
        {'start':'2026-11-10T00:00:00+01:00','end':'2026-11-10T08:00:00+01:00','tariff':'NT'},
        {'start':'2026-11-10T08:00:00+01:00','end':'2026-11-10T23:59:59+01:00','tariff':'VT'}]})
    monkeypatch.setattr(hdo, 'schedule_for', lambda entity: rows)
    expr = nordpool.sql_buy_cost_expr('v.spot', 'v.t')
    for when in ('2026-11-10T06:59:59+00:00','2026-11-10T07:00:00+00:00','2026-11-11T01:00:00+00:00'):
        t=datetime.fromisoformat(when)
        for spot in (-.5,0,2):
            actual=db.execute(f'SELECT {expr} FROM (SELECT %s::timestamptz AS t, %s::numeric AS spot) AS v',(t,spot)).fetchone()[0]
            assert float(actual)==pytest.approx(nordpool.full_buy_cost(spot,t))


def test_ote_attributes_preserve_quarters_negative_values_and_gaps():
    start=datetime(2026,10,24,22,tzinfo=timezone.utc)
    attrs={(start+timedelta(minutes=15*i)).isoformat(): (-500 if i==0 else 1200) for i in range(100) if i!=3}
    rows=nordpool.parse_price_attributes(attrs,'Kč/MWh')
    assert len(rows)==99 and rows[0][2]==-.5
    assert rows[2][1]==start+timedelta(minutes=45)
    assert rows[3][0]==start+timedelta(minutes=60)


@pytest.mark.parametrize('unit,valid',[('CZK/kWh',True),('Kč/MWh',True),(' Kč/kWh ',True),('EUR/MWh',False),('CZK/MJ',False),('CZK/',False),('',False)])
def test_czech_units_require_known_currency_and_energy_unit(unit,valid):
    assert nordpool._is_czech_price_unit(unit) is valid


def test_cez_all_day_vt_may_mean_missing_schedule(monkeypatch):
    rows = hdo.parse_schedule({'schedule': [
        {'start':'2026-11-10T00:00:00+01:00', 'end':'2026-11-10T23:59:59+01:00', 'tariff':'VT'}]})
    monkeypatch.setattr(hdo, 'schedule_for', lambda entity: rows)
    assert hdo.purchase_at(datetime(2026, 11, 10, 12, tzinfo=timezone.utc),
                           {'hdo_entity':'sensor.hdo','buy_nt':4,'buy_vt':2}) == 4


def test_other_sources_keep_hourly_intervals_when_cadence_changes():
    attrs={'prices':[{'start':'2026-11-10T00:00:00+01:00','price':1},
                     {'start':'2026-11-10T01:00:00+01:00','price':2},
                     {'start':'2026-11-10T01:15:00+01:00','price':3}]}
    rows=nordpool.parse_price_attributes(attrs,'EUR/kWh')
    assert rows[0][1]-rows[0][0]==timedelta(hours=1)
    assert rows[1][1]-rows[1][0]==timedelta(minutes=15)


def test_price_settings_api_preserves_valid_hdo_on_partial_update(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    from unittest.mock import Mock

    monkeypatch.chdir(Path(__file__).resolve().parents[1] / 'webdashboard')
    import webdashboard.app as app
    monkeypatch.setattr(app.AUTH, 'session', lambda request: ('owner', 'test'))
    monkeypatch.setattr(ew_settings, 'PATH', str(tmp_path / 'settings.json'))
    ew_settings._cache.update(mtime=None, data={})
    for key in ('PRICE_COUNTRY', 'PRICE_BUY_MODE', 'PRICE_HDO_ENTITY', 'PRICE_BUY_NT', 'PRICE_BUY_VT'):
        monkeypatch.delenv(key, raising=False)
    def request(body):
        async def json_body(): return body
        return Mock(json=json_body)
    result=asyncio.run(app.price_settings_set(request({'country':'CZ','area':'CZ','buy_mode':'hdo',
        'hdo_entity':'sensor.cez_hdo','hdo_price_source':'manual','buy_nt':'2,5','buy_vt':'5.1'})))
    assert result=={'ok':True}
    assert nordpool.cost_settings()['buy_nt']==2.5
    result=asyncio.run(app.price_settings_set(request({'country':'CZ','area':'CZ','buy_nt':''})))
    assert result.status_code==400
    assert nordpool.cost_settings()['buy_nt']==2.5
    result=asyncio.run(app.price_settings_get())
    assert result['country']=='CZ' and result['buy_mode']=='hdo'
