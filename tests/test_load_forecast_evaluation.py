from datetime import datetime,timedelta,timezone
import pytest
from load_forecast_evaluation import base_load_w,aggregate,evaluate

START=datetime(2026,10,1,tzinfo=timezone.utc)


@pytest.mark.parametrize('grid,pv,battery,loads,expected',[
    (2000,0,0,[],2000),(-1000,4000,1000,[],2000),
    (0,0,-2000,[],2000),(2000,4000,2000,[1000,500],2500),
])
def test_signed_boundary_and_explicit_excluded_loads(grid,pv,battery,loads,expected):
    assert base_load_w(grid,pv,battery,loads)==expected


@pytest.mark.parametrize('values',[(None,0,0,[]),(0,-1,0,[]),(0,0,0,[1]),(0,0,0,[-1]),(float('nan'),0,0,[])])
def test_missing_or_inconsistent_signals_are_not_zero_filled(values):
    with pytest.raises(ValueError):base_load_w(*values)


def test_aggregation_rejects_gaps_and_does_not_double_count_controlled_loads():
    ss=[dict(timestamp=START+timedelta(seconds=i),grid_w=3000,pv_w=0,battery_w=0,controlled_w=[1000])
        for i in range(0,1801,60)]
    rows,coverage=aggregate(ss)
    assert len(rows)==2 and rows[0]['kw']==2
    del ss[4:8]
    rows,coverage=aggregate(ss)
    assert len(rows)==1 and coverage['rejected_sample_intervals']==1


def history():
    return [{'t':START.timestamp()+i*900,'kw':2 if i<7*96 else 1} for i in range(8*96)]


def test_causal_comparison_reports_metrics_but_never_adopts():
    r=evaluate(history(),START+timedelta(days=7))
    assert r['candidate']['mae_kw']<r['baseline']['mae_kw']
    assert not r['adoption_ready'] and r['economic_evaluation'] is None
    assert r['training_quarters']==672


def test_target_and_future_observations_cannot_change_earlier_predictions():
    data=history();a=evaluate(data,START+timedelta(days=7))
    for row in data[7*96:]:row['kw']=20
    b=evaluate(data,START+timedelta(days=7))
    assert a['predictions'][0]['candidate_kw']==b['predictions'][0]['candidate_kw']
    assert a['predictions'][0]['baseline_kw']==b['predictions'][0]['baseline_kw']
    # Previous completed test observations are legitimately available to the next origin.
    assert a['predictions'][4]['candidate_kw']!=b['predictions'][4]['candidate_kw']


def test_sparse_or_duplicate_history_rejected():
    with pytest.raises(ValueError):evaluate(history()[:10],START+timedelta(days=7))
    with pytest.raises(ValueError):evaluate(history()+[history()[0]],START+timedelta(days=7))


def test_offline_cli_has_no_adoption_side_effects(tmp_path):
    import json,subprocess,sys
    samples=[dict(timestamp=(START+timedelta(seconds=i)).isoformat(),grid_w=2000,pv_w=0,
                  battery_w=0,controlled_w=[]) for i in range(0,8*86400+1,60)]
    path=tmp_path/'samples.json';path.write_text(json.dumps(samples))
    run=subprocess.run([sys.executable,'scripts/evaluate_household_forecast.py',str(path),
                        '--split',(START+timedelta(days=7)).isoformat(),'--timezone','UTC'],
                       text=True,capture_output=True)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert result['evaluation_quarters']==96 and not result['adoption_ready']
    assert list(tmp_path.iterdir())==[path]


def test_dst_repeated_hours_remain_distinct_physical_quarters():
    from zoneinfo import ZoneInfo
    start=datetime(2026,10,25,0,tzinfo=timezone.utc);zone=ZoneInfo('Europe/Stockholm')
    samples=[dict(timestamp=(start+timedelta(seconds=i)).astimezone(zone),grid_w=1000,
                  pv_w=0,battery_w=0) for i in range(0,7201,60)]
    rows,_=aggregate(samples)
    assert len(rows)==8 and len({r['t'] for r in rows})==8
