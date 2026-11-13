"""Offline load-signal validation and causal forecast comparison; no runtime adoption."""
from collections import defaultdict
from datetime import datetime, timedelta
import math
import statistics
from zoneinfo import ZoneInfo


def number(value):
    if value is None or isinstance(value,bool) or not math.isfinite(float(value)):
        raise ValueError('Finite measurements required')
    return float(value)


def epoch(value):
    dt=datetime.fromisoformat(value) if isinstance(value,str) else value
    if dt.utcoffset() is None:raise ValueError('Timezone-aware timestamp required')
    return dt.timestamp()


def base_load_w(grid_w,pv_w,battery_w,controlled_w=()):
    """AC house boundary: grid import + PV - battery charge - excluded loads.

    PV and excluded loads must be nonnegative; grid/battery are signed. Missing
    readings remain missing, not zero. Negative residuals are invalid, not clipped.
    """
    grid,pv,battery=map(number,(grid_w,pv_w,battery_w))
    excluded=[number(v) for v in controlled_w]
    if pv<0 or any(v<0 for v in excluded):raise ValueError('Unsigned loads/PV must be nonnegative')
    base=grid+pv-battery-sum(excluded)
    if base<0:raise ValueError('Energy balance inconsistent with excluded loads')
    return base


def aggregate(samples,min_coverage=.9,max_gap_s=90):
    """Physical UTC quarters from adjacent samples; exclude invalid/gapped intervals."""
    if not 0<min_coverage<=1 or not 0<max_gap_s<=300:raise ValueError('Invalid coverage policy')
    samples=sorted(samples,key=lambda s:epoch(s['timestamp']))
    times=[epoch(s['timestamp']) for s in samples]
    if len(set(times))!=len(times):raise ValueError('Duplicate sample timestamp')
    sums=defaultdict(lambda:[0.,0.])
    rejected=0
    for a,b,start,end in zip(samples,samples[1:],times,times[1:]):
        if end-start>max_gap_s:rejected+=1;continue
        try:
            watts=base_load_w(a.get('grid_w'),a.get('pv_w'),a.get('battery_w'),a.get('controlled_w',()))
            base_load_w(b.get('grid_w'),b.get('pv_w'),b.get('battery_w'),b.get('controlled_w',()))
        except (ValueError,TypeError):rejected+=1;continue
        while start<end:
            t=int(start//900)*900;stop=min(end,t+900)
            sums[t][0]+=watts*(stop-start);sums[t][1]+=stop-start;start=stop
    rows=[{'t':t,'kw':energy/seconds/1000,'coverage':seconds/900}
          for t,(energy,seconds) in sorted(sums.items()) if seconds/900>=min_coverage]
    return rows,{'rejected_sample_intervals':rejected,'accepted_quarters':len(rows),
                 'integration':'Left sample held only to next sample within max_gap_s',
                 'minimum_quarter_coverage':min_coverage,'max_gap_s':max_gap_s}


def percentile(values,q):
    values=sorted(values)
    i=(len(values)-1)*q;lo=int(i);hi=min(len(values)-1,lo+1)
    return values[lo]+(values[hi]-values[lo])*(i-lo)


def forecasts_at_origin(rows,origin,targets,timezone_name='Europe/Stockholm'):
    """One frozen horizon: observations at/after origin never become features."""
    zone=ZoneInfo(timezone_name)
    history={}
    profile=defaultdict(list)
    local=defaultdict(list)
    for row in rows:
        t=number(row['t']);kw=number(row['kw'])
        if t%900 or kw<0 or t in history:raise ValueError('Invalid or duplicate quarter')
        history[t]=kw
    history={t:kw for t,kw in history.items() if t+900<=origin}
    if len(history)<672:raise ValueError('At least seven days of completed training quarters required')
    for t,kw in history.items():
        dt=datetime.fromtimestamp(t,zone)
        profile[dt.weekday(),dt.hour].append(kw)
        local[dt.date(),dt.hour,dt.minute,dt.fold].append(kw)
    recent=[history[t] for t in (origin-900,origin-1800,origin-2700,origin-3600) if t in history]
    predictions=[]
    for t in targets:
        dt=datetime.fromtimestamp(t,zone)
        values=profile[dt.weekday(),dt.hour]
        baseline=max(1.,min(6.,percentile(values,.85))) if values else 2.5
        support=list(recent)
        for days in (1,7):
            day=(dt-timedelta(days=days)).date()
            values=local.get((day,dt.hour,dt.minute,dt.fold),[])
            if values:support.append(statistics.median(values))
        candidate=.5*baseline+.5*statistics.median(support) if support else baseline
        predictions.append({'t':t,'baseline_kw':baseline,'candidate_kw':max(.05,min(25.,candidate))})
    return predictions


def evaluate_planner_snapshot(rows,snapshot,timezone_name='Europe/Stockholm'):
    """Paired offline cash-flow counterfactual, never an adoption decision.

    Only exact quarter-boundary snapshots with supported simulation semantics
    are accepted. Exogenous price/PV/EV inputs stay identical in both runs.
    """
    import battery_plan
    import plan_snapshot
    if not plan_snapshot.replay(snapshot)['matches']:
        raise ValueError('Recorded planner output cannot be reproduced')
    inputs=plan_snapshot.normalize_inputs(**snapshot['inputs'])
    slots,params=inputs['slots'],inputs['params']
    origin=epoch(snapshot['made_at']);targets=[epoch(s['t']) for s in slots]
    if origin%900 or targets[0]!=origin:
        raise ValueError('Initial SOC and first slot must share an exact quarter-boundary origin')
    if not params['allow_export'] or params['ev_mode']!='block' or params['balance_target_kwh']:
        raise ValueError('Simulator supports export-enabled, EV-blocking, non-balancing snapshots only')
    if not (0<=params['reserve_kwh']<=params['soc0_kwh']<=params['max_kwh']<=params['capacity_kwh']
            and 0<params['eff']<=1 and params['charge_kw']>=0 and params['discharge_kw']>=0):
        raise ValueError('Invalid physical battery parameters')
    predictions=forecasts_at_origin(rows,origin,targets,timezone_name)
    actual={number(r['t']):number(r['kw']) for r in rows}
    if any(t not in actual for t in targets):raise ValueError('Missing realized load quarter')
    if any(s['solar_kw']<0 or s['ev_kw']<0 for s in slots):raise ValueError('Invalid unsigned exogenous load')
    realized=[{**slot,'load_kw':actual[t]} for slot,t in zip(slots,targets)]
    results={}
    for label in ('baseline','candidate'):
        forecast=[{**slot,'load_kw':p[label+'_kw']} for slot,p in zip(slots,predictions)]
        plan=battery_plan.optimize(forecast,**params)
        actions=[r['action'] for r in plan['rows']]
        if len(actions)!=len(slots):raise ValueError('Incomplete counterfactual plan')
        _,simulation=battery_plan.simulate(realized,params['soc0_kwh'],actions,
            params['capacity_kwh'],params['reserve_kwh'],params['max_kwh'],
            params['charge_kw'],params['discharge_kw'],params['eff'])
        cash=sum(battery_plan._cost(r['grid_kw'],s['buy'],s['sell']) for r,s in zip(simulation,slots))
        results[label]={'energy_cash_cost':cash,'ending_soc_kwh':simulation[-1]['soc_kwh'],
            'soc_bounds_respected':all(params['reserve_kwh']-1e-9<=r['soc_kwh']<=params['max_kwh']+1e-9 for r in simulation),
            'actions':actions}
    return {'plan_id':snapshot['plan_id'],'origin':origin,'quarters':len(slots),
            'results':results,'predictions':predictions,
            'candidate_minus_baseline_cash_cost':results['candidate']['energy_cash_cost']-results['baseline']['energy_cash_cost'],
            'adoption_ready':False,
            'scope':'Simulated energy cash flow using recorded prices/PV/EV and realized load; excludes wear, switching and terminal energy valuation. Different ending SOC prevents interpreting cash delta as savings. No fuse/comfort or hardware qualification.'}


def evaluate(rows,split_at,timezone_name='Europe/Stockholm',min_train=7*96,min_test=96,
             min_relative_mae_improvement=.05):
    """Frozen p85 weekday/hour baseline vs causal recent/historical blend.

    Only slots that ended before the forecast origin can feed candidate features.
    Test observations may feed later forecasts, as they would in a rolling deployment.
    No held-out target is used to predict itself. No automatic model selection.
    """
    split=epoch(split_at);zone=ZoneInfo(timezone_name)
    rows=sorted(rows,key=lambda s:s['t'])
    if len({r['t'] for r in rows})!=len(rows):raise ValueError('Duplicate quarter')
    for r in rows:
        if not number(r['t'])%900==0 or number(r['kw'])<0:raise ValueError('Invalid quarter')
    train=[r for r in rows if r['t']+900<=split]
    test=[r for r in rows if r['t']>=split]
    if len(train)<min_train or len(test)<min_test:raise ValueError('Insufficient training/evaluation coverage')
    profile=defaultdict(list)
    def key(t):
        dt=datetime.fromtimestamp(t,zone);return dt.weekday(),dt.hour
    for r in train:profile[key(r['t'])].append(r['kw'])
    history={r['t']:r['kw'] for r in train}
    local_history=defaultdict(list)
    def local_key(t):
        dt=datetime.fromtimestamp(t,zone)
        return dt.date(),dt.hour,dt.minute,dt.fold
    for r in train:local_history[local_key(r['t'])].append(r['kw'])
    predictions=[]
    for r in test:
        baseline=max(1.,min(6.,percentile(profile[key(r['t'])],.85))) if profile[key(r['t'])] else 2.5
        # Only recently completed physical quarters, not arbitrarily old last values.
        recent=[history[t] for t in (r['t']-900,r['t']-1800,r['t']-2700,r['t']-3600) if t in history]
        # Match local weekday/time histories; do not confuse the repeated DST hour.
        current=datetime.fromtimestamp(r['t'],zone)
        matching=[]
        for days in (1,7):
            target=current-timedelta(days=days)
            candidates=local_history.get((target.date(),current.hour,current.minute,current.fold),[])
            if candidates:matching.append(statistics.median(candidates))
        support=recent+matching
        candidate=.5*baseline+.5*statistics.median(support) if support else baseline
        candidate=max(0.05,min(25.,candidate))
        predictions.append({'t':r['t'],'actual_kw':r['kw'],'baseline_kw':baseline,
                            'candidate_kw':candidate,'support_count':len(support)})
        history[r['t']]=r['kw']  # becomes usable only for subsequent forecast origins
        local_history[local_key(r['t'])].append(r['kw'])
    def metrics(name):
        errors=[r[name]-r['actual_kw'] for r in predictions]
        return {'mae_kw':sum(abs(e) for e in errors)/len(errors),
                'rmse_kw':math.sqrt(sum(e*e for e in errors)/len(errors))}
    base,candidate=metrics('baseline_kw'),metrics('candidate_kw')
    improvement=(base['mae_kw']-candidate['mae_kw'])/base['mae_kw'] if base['mae_kw'] else 0
    return {'training_quarters':len(train),'evaluation_quarters':len(test),'split_at':split_at.isoformat() if hasattr(split_at,'isoformat') else split_at,
            'baseline':base,'candidate':candidate,'relative_mae_improvement':improvement,
            'required_relative_mae_improvement':min_relative_mae_improvement,
            'forecast_error_gate_passed':improvement>=min_relative_mae_improvement and candidate['rmse_kw']<=base['rmse_kw'],
            'economic_evaluation':None,'adoption_ready':False,
            'remaining_gate':'Paired downstream planning/cost and constraint evaluation on recorded inputs required',
            'baseline_definition':'P85 weekday/hour clamped 1–6 kW; 2.5 kW sparse fallback, on reconstructed signal',
            'predictions':predictions}
