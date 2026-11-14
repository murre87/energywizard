"""Audit a captured local REST point dictionary without contacting a heater."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from nibe_hot_water_audit import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local JSON with points and explicit role bindings")
    args = parser.parse_args()
    if args.input.stat().st_size > 2_000_000:
        parser.error("Input limited to 2 MB")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        report = audit(data["points"], data["bindings"])
    except (ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
