"""Read-only local export; no source timestamps are invented or backfilled."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from energy_source_export import export, validate_window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="Offset-aware ISO date, inclusive")
    parser.add_argument("--until", required=True, help="Offset-aware ISO date, inclusive endpoint sample")
    parser.add_argument("--limit", type=int, default=100000)
    args = parser.parse_args()
    try:
        since, until = validate_window(args.since, args.until, args.limit)
    except (ValueError, TypeError, OverflowError) as exc:
        parser.error(str(exc))
    try:
        from database_engine import engine
        with engine.connect() as connection:
            result = export(connection, since, until, args.limit)
    except ValueError as exc:
        parser.error(str(exc) if str(exc) == "Too many rows; narrow the export window" else
                     "Could not read source evidence; check local database availability and schema")
    except Exception:
        parser.error("Could not read source evidence; check local database availability and schema")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
