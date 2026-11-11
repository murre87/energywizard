"""Read-only report from local snapshots and sensor_log. No control or uploads."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'smartbox'))
import plan_snapshot
import plan_delivery


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', required=True, help='Inclusive ISO timestamp with UTC offset')
    p.add_argument('--end', required=True, help='Exclusive ISO timestamp with UTC offset')
    p.add_argument('--directory', default='/data/planning-snapshots')
    args=p.parse_args()
    if not 0 < plan_delivery.utc(args.end)-plan_delivery.utc(args.start) <= 7*86400:
        p.error('Report windows must be between zero and seven days')
    snapshots=[]
    for path in Path(args.directory).glob('*.json'):
        if path.stat().st_size > plan_snapshot.MAX_BYTES:
            raise ValueError('Oversize snapshot')
        snap=json.loads(path.read_text())
        # Integrity only; reporting may inspect evidence from older planner source.
        import hashlib
        content={k:v for k,v in snap.items() if k!='plan_id'}
        if snap.get('schema_version') != plan_snapshot.SCHEMA or hashlib.sha256(plan_snapshot.canonical(content).encode()).hexdigest()!=snap.get('plan_id'):
            raise ValueError('Invalid snapshot')
        snapshots.append(snap)
    from sqlalchemy import text
    from database_engine import engine
    with engine.connect() as c:
        rows=c.execute(text('''SELECT timestamp, net_power, battery_power_w, battery_plan_id, battery_plan_rule, pv_power_w
            FROM sensor_log WHERE timestamp >= CAST(:a AS timestamptz) - interval '90 seconds'
            AND timestamp <= CAST(:b AS timestamptz) + interval '90 seconds' ORDER BY timestamp'''),
            {'a':args.start,'b':args.end}).fetchall()
    samples=[dict(timestamp=t,grid_w=g,battery_w=b,plan_id=i,rule=r,pv_w=pv) for t,g,b,i,r,pv in rows]
    print(json.dumps(plan_delivery.report(snapshots,samples,args.start,args.end),indent=2))


if __name__=='__main__': main()
