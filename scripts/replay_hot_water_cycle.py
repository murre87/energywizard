"""Replay simulated hot-water cycle events into an explicit private local journal."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from hot_water_cycle import open_journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Frozen proposal, explicit policy and events JSON")
    parser.add_argument("--journal", type=Path, required=True, help="Private single-owner simulation file")
    args = parser.parse_args()
    if args.input.resolve() == args.journal.resolve():
        parser.error("Input and journal must be separate files")
    if args.input.stat().st_size > 2_000_000:
        parser.error("Input limited to 2 MB")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if len(data["events"]) > 1000:
            raise ValueError("At most 1000 replay events")
        cycle = open_journal(args.journal)
        results = [cycle.arm(data["proposal"], **data["policy"])]
        for event in data["events"]:
            if event["kind"] == "tick":
                results.append(cycle.tick(**event["inputs"]))
            elif event["kind"] == "acknowledge":
                results.append(cycle.acknowledge(cycle.state.get("token"), **event["inputs"]))
            else:
                raise ValueError("Unknown replay event kind")
    except (ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({"simulation_only": True, "events": results}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
