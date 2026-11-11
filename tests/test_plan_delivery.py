from datetime import datetime, timedelta, timezone
import inspect
import pytest
import battery_plan
import plan_snapshot as S
from plan_delivery import report

START = datetime(2026,10,25,0,45,tzinfo=timezone.utc)


def snapshot(at=START, price=2):
    slots = [{'t':START,'buy':price,'sell':1,'load_kw':2,'solar_kw':0,'ev_kw':0}]
    p=dict(soc0_kwh=0,capacity_kwh=2,reserve_kwh=0,max_kwh=2,charge_kw=1,discharge_kw=1)
    return S.build(slots,p,battery_plan.optimize(slots,**p),at)


def measurements(p, seconds=900):
    return [dict(timestamp=START+timedelta(seconds=i),plan_id=p['plan_id'],
                 grid_w=2000,battery_w=0,pv_w=0,rule='plan') for i in range(0,seconds+1,60)]


def test_complete_measurements_separate_cash_from_modeled_wear():
    p=snapshot();r=report([p],measurements(p),START,START+timedelta(minutes=15))
    assert r['complete'] and r['coverage_fraction']==1
    assert r['measured_import_kwh']==pytest.approx(.5)
    assert r['measured_energy_cost']==pytest.approx(1)
    assert r['full_window_cost_difference']==pytest.approx(0)
    assert r['counterfactual_savings'] is None
    assert r['household_forecast_error_kwh']==pytest.approx(0)


def test_export_and_battery_signs_have_correct_energy_balance():
    p=snapshot();ss=measurements(p)
    for s in ss:s.update(grid_w=-1000,battery_w=-2000,pv_w=1000)
    r=report([p],ss,START,START+timedelta(minutes=15))
    assert r['measured_export_kwh']==pytest.approx(.25)
    assert r['measured_battery_discharge_kwh']==pytest.approx(.5)
    assert r['measured_energy_cost']==pytest.approx(-.25)
    assert r['measured_household_kwh']==pytest.approx(.5)
    assert r['solar_forecast_error_kwh']==pytest.approx(.25)


def test_missing_samples_stay_incomplete_not_zero_filled():
    p=snapshot();ss=measurements(p)
    del ss[5:9]
    r=report([p],ss,START,START+timedelta(minutes=15))
    assert not r['complete'] and r['coverage_seconds']==600
    assert r['full_window_cost_difference'] is None
    assert r['measured_energy_cost']==pytest.approx(2*2*600/3600)


def test_replan_mid_interval_splits_by_captured_activation():
    old=snapshot();new=snapshot(START+timedelta(seconds=30),price=4)
    ss=measurements(old,60);ss[1]['plan_id']=new['plan_id']
    r=report([old,new],ss,START,START+timedelta(seconds=60))
    assert r['complete']
    assert r['measured_energy_cost']==pytest.approx(2*(2*30+4*30)/3600)
    assert len(r['plan_ids'])==2


def test_missing_plan_identity_or_snapshot_is_not_inferred():
    p=snapshot();ss=measurements(p)
    for s in ss:s['plan_id']=None
    assert report([p],ss,START,START+timedelta(minutes=15))['coverage_seconds']==0
    assert report([],measurements(p),START,START+timedelta(minutes=15))['coverage_seconds']==0


def test_stale_invalid_duplicate_and_missing_pv():
    p=snapshot();ss=measurements(p,60)
    ss[0]['pv_w']=None
    r=report([p],ss,START,START+timedelta(seconds=60))
    assert r['complete'] and r['forecast_coverage_seconds']==0
    ss[0]['grid_w']=float('nan')
    assert report([p],ss,START,START+timedelta(seconds=60))['coverage_seconds']==0
    with pytest.raises(ValueError):report([p],[ss[0],ss[0]],START,START+timedelta(seconds=60))
    with pytest.raises(ValueError):report([p],[],START,START)
    with pytest.raises(ValueError):report([p],[],START.replace(tzinfo=None),START+timedelta(seconds=60))


def test_real_postgres_logs_plan_identity_without_changing_existing_measurements(smartbox):
    kwargs={k: None for k,v in inspect.signature(smartbox.log_status).parameters.items()
            if v.default is inspect.Parameter.empty}
    kwargs.update(pump={},solar={'battery_plan_id':'a'*64,'battery_plan_rule':'plan',
                                'battery_power_w':-1000},net_power=2000)
    smartbox.log_status(**kwargs)
    with smartbox.get_db() as c:
        row=c.execute('SELECT battery_plan_id,battery_plan_rule,battery_power_w,net_power FROM sensor_log ORDER BY timestamp DESC LIMIT 1').fetchone()
    assert row==('a'*64,'plan',-1000,2000)


def test_physical_quarter_across_repeated_dst_hour():
    from zoneinfo import ZoneInfo
    p=snapshot();zone=ZoneInfo('Europe/Stockholm')
    ss=measurements(p)
    for s in ss:s['timestamp']=s['timestamp'].astimezone(zone)
    start=START.astimezone(zone);end=(START+timedelta(minutes=15)).astimezone(zone)
    assert start.utcoffset()!=end.utcoffset()
    r=report([p],ss,start,end)
    assert r['complete'] and r['duration_seconds']==900
