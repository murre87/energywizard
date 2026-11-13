# FTW changelog review — #199

Reviewed 2026-11-13 against EnergyWizard `00f4d51`. The requested
[`v0.160.0-beta.1` tag](https://github.com/srcfl/ftw/tree/4ae7a925018c0fb080331aa9f2fd77b543c9467f)
resolves to `4ae7a925018c0fb080331aa9f2fd77b543c9467f`; its
[changelog](https://github.com/srcfl/ftw/blob/4ae7a925018c0fb080331aa9f2fd77b543c9467f/CHANGELOG.md)
heads the relevant section **0.160.0**. This is that pinned release review,
not a review of a moving newer FTW release.

## What is relevant now

The reviewed changes describe a control journal and planned/delivered slot
energy, more precise explanations of charger-imposed current limits, fresh
pilot-current evidence, sustained vehicle-stop handling, truthful queued
notification status and recovery of notification records after database pressure.
Earlier sections cover not-following notifications and the current tariff hour.

Several recommendations in the issue's earlier comment are already delivered:

| Capability | Existing EnergyWizard evidence | Remaining gap |
| --- | --- | --- |
| Requested versus actual control | `smartbox/control_journal.py`, `battery_follow.py`; History views. | Current journal entries do not by themselves prove energy delivery over a whole slot. |
| Plan identity and interval energy | `plan_snapshot.py`, `plan_delivery.py`, `battery_commands.py`. | Join the existing evidence for support rather than build another journal. |
| Notification outcomes | `notify_log.py`, `notifier.py`. | HA acceptance is not phone delivery; failed history writes can still lose an evidence row. |
| Missed EV goals | `ev_missed.py` and its main-loop integration. | A vehicle stop is not proof of full SOC or a charger-imposed limit. |
| Tariff hour already running | `capacity_tariff.py`, main-loop hourly budget. | No reason to port a second tariff planner. |

## Ranked implementation proposals

1. **Fresh charger-limit explanations** — 1–2 days plus device validation.
   Extend optional read-only charger evidence with effective offered current,
   observation time and an optional reported limiting reason. Start at
   `drivers/charger.py`, `drivers/charger_easee.py`, `homeassistant.py` and
   `control_journal.py`. Use a cause only when fresh evidence explains the
   measured shortfall; otherwise retain an unknown-cause explanation. Do not
   infer load balancing merely from low measured current or relax fuse limits.
   Test stale/future evidence, phase conversion, zero/low draw, unknown cause
   and a car stopping while current is offered. EN/CS text parity is required.
2. **Join existing plan/command/delivery evidence** — 1–3 days.
   Add a read-only support view joining plan identity, command evidence,
   measured energy and coverage. Reuse #253/#254/#256 Stage A; missing telemetry
   remains incomplete. Test superseded plans, DST quarters and telemetry gaps.
   A percentage must identify its denominator and coverage rather than imply
   unmeasured minutes followed the plan.
3. **Bounded retry of history persistence only** — 1–2 days.
   Evaluate a bounded, deduplicated queue for notification-history rows during
   database pressure. Keep the original event time and existing redaction and
   retention. Never resend a push as a side effect of saving its history.
   Test full queue, repeated failure, recovery and duplicate event identity.

These are proposed independent changes, not an instruction to enable new control
or claim reporter recovery. Items 1 and 2 should precede a wider diagnostics UI.

## Exclusions and verification limits

Do not import Energyplan workers or change the optimizer based on a changelog.
The pinned [licensing scope](https://github.com/srcfl/ftw/blob/4ae7a925018c0fb080331aa9f2fd77b543c9467f/LICENSING.md)
distinguishes AGPL-covered FTW code from separately licensed worker binaries;
the [LICENSE](https://github.com/srcfl/ftw/blob/4ae7a925018c0fb080331aa9f2fd77b543c9467f/LICENSE)
and individual notices need their own review before copying or bundling anything.
Zap firmware/cloud delivery are outside this repository. No upstream code was
copied, run or benchmarked; no hardware or installation comparison was performed.
The research deliverable is complete without implementing all these proposals.
