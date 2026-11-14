"""Bounded read-only export of sanitized source snapshots, never legacy filling."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from energy_source_evidence import log_value
from hot_water_residual import CONTRACT


def validate_window(since, until, limit=100000):
    dates = [datetime.fromisoformat(v) if isinstance(v, str) else v for v in (since, until)]
    if any(not isinstance(v, datetime) or v.utcoffset() is None for v in dates):
        raise ValueError("Export dates require UTC offsets")
    since, until = (v.astimezone(timezone.utc) for v in dates)
    if not timedelta(0) < until-since <= timedelta(days=31) or type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("Export limited to 31 days and 100000 rows")
    return since, until


def export(connection, since, until, limit=100000):
    """Use a fresh SQLAlchemy connection/transaction; output includes endpoints."""
    since, until = validate_window(since, until, limit)
    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout = '2s'"))
    rows = connection.execute(text("SELECT timestamp,energy_source_evidence FROM sensor_log "
                                   "WHERE timestamp >= :a AND timestamp <= :b ORDER BY timestamp LIMIT :n"),
                              {"a": since, "b": until, "n": limit+1}).fetchall()
    if len(rows) > limit:
        raise ValueError("Too many rows; narrow the export window")
    samples, missing, invalid = [], 0, 0
    for row in rows:
        gap = {"timestamp": row[0].isoformat(), "evidence_missing": True}
        if row[1] is None:
            missing += 1
            samples.append(gap)
            continue
        snapshot = log_value(row[1])
        if snapshot is None:
            invalid += 1
            samples.append(gap)
            continue
        at = datetime.fromisoformat(snapshot["timestamp"])
        if not since <= at <= until:
            invalid += 1
            samples.append(gap)
            continue
        samples.append(snapshot)
    return {"contract": {**CONTRACT, "excluded_loads": ["hot_water"]}, "samples": samples,
            "export_report": {"rows_read": len(rows), "missing_evidence_rows": missing,
                              "invalid_evidence_rows": invalid}, "adoption_ready": False}
