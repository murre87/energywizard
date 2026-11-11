"""Offline, local-only comparison. Input JSON is never uploaded; no runtime settings change."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'smartbox'))
from load_forecast_evaluation import aggregate,evaluate

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('samples',help='JSON array: timestamp, grid_w, pv_w, battery_w, controlled_w list')
    p.add_argument('--split',required=True,help='Chronological evaluation start, ISO time with offset')
    p.add_argument('--timezone',default='Europe/Stockholm')
    args=p.parse_args()
    path=Path(args.samples)
    if path.stat().st_size>50_000_000:p.error('Input limited to 50 MB')
    rows,coverage=aggregate(json.loads(path.read_text()))
    result=evaluate(rows,args.split,args.timezone)
    result['coverage']=coverage
    print(json.dumps(result,indent=2))
