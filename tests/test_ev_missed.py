"""Missad morgonladdning: orsakstext + när notisen ska gå (#Leaf 11/12 nov)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import ev_missed

TZ = ZoneInfo("Europe/Stockholm")


def test_due_once_after_deadline():
    deadline = datetime(2026, 11, 12, 6, 0, tzinfo=TZ)
    now = deadline + timedelta(minutes=5)
    assert ev_missed.due_missed_alert(
        soc=32, target_soc=50, plugged_in=True, now=now, deadline=deadline, already_key=None,
    )
    assert not ev_missed.due_missed_alert(
        soc=32, target_soc=50, plugged_in=True, now=now, deadline=deadline, already_key=deadline,
    )
    assert not ev_missed.due_missed_alert(
        soc=55, target_soc=50, plugged_in=True, now=now, deadline=deadline, already_key=None,
    )


def test_explain_sibling_took_fuse():
    t = ev_missed.explain(
        soc=32, target_soc=50, ordered_a=0, power_kw=0, status="awaiting_start",
        minutes_zero_order=120, minutes_stalled=0,
        sibling_name="Tesla", sibling_got_power=True,
    )
    assert "0 A" in t and "Tesla" in t and "50" in t


def test_explain_awaiting_start_stall():
    t = ev_missed.explain(
        soc=40, target_soc=50, ordered_a=10, power_kw=0, status="awaiting_start",
        minutes_zero_order=0, minutes_stalled=45,
    )
    assert "awaiting_start" in t and "0 kW" in t
