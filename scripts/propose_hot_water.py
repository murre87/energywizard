"""Evaluate a local hot-water deadline proposal; never controls equipment."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from hot_water_plan import propose, reserve_load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Frozen request, prices and optional residual forecast JSON")
    args = parser.parse_args()
    if args.input.stat().st_size > 2_000_000:
        parser.error("Input limited to 2 MB")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        proposal = propose(data["prices"], **data["request"])
        result = {"proposal": proposal}
        if "forecast" in data and proposal["state"] == "proposed":
            result["battery_forecast"] = reserve_load(data["forecast"], proposal,
                                                       baseline_contract=data.get("baseline_contract"))
    except (ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
