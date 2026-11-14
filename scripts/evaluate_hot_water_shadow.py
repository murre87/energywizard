"""End-to-end frozen hot-water handover replay, with no network or device writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from hot_water_cycle import open_journal
from hot_water_shadow import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--journal", required=True, type=Path, help="Private single-owner simulation journal")
    args = parser.parse_args()
    if args.input.resolve() == args.journal.resolve():
        parser.error("Input and journal must be separate files")
    if args.input.stat().st_size > 2_000_000:
        parser.error("Input limited to 2 MB")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = evaluate(data, open_journal(args.journal))
    except (ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
