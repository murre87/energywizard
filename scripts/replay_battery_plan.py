"""Offline replay: python scripts/replay_battery_plan.py snapshot.json. No device writes."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'smartbox'))
import plan_snapshot

if __name__ == '__main__':
    path = Path(sys.argv[1])
    if path.stat().st_size > plan_snapshot.MAX_BYTES:
        raise SystemExit('Snapshot exceeds size limit')
    try:
        result = plan_snapshot.replay(json.loads(path.read_text()))
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['matches'] else 1)
