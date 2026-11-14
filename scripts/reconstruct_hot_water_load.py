"""Reconstruct a dated AC residual signal locally; never changes runtime forecasts."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from hot_water_residual import reconstruct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local JSON contract and dated measurement samples")
    parser.add_argument("--max-age-s", type=float, default=90)
    parser.add_argument("--max-skew-s", type=float, default=5)
    parser.add_argument("--max-gap-s", type=float, default=90)
    parser.add_argument("--min-coverage", type=float, default=.9)
    parser.add_argument("--allow-receipt", action="store_true", help="Explicitly accept receipt-time evidence for offline comparison")
    args = parser.parse_args()
    if args.input.stat().st_size > 50_000_000:
        parser.error("Input limited to 50 MB")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = reconstruct(data["samples"], data["contract"], max_age_s=args.max_age_s,
                             max_skew_s=args.max_skew_s, max_gap_s=args.max_gap_s,
                             min_coverage=args.min_coverage, allow_receipt=args.allow_receipt)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
