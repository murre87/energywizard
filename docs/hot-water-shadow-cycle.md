# Hot-water shadow cycle — #407

`hot_water_cycle.ShadowCycle` evaluates a **simulation only**. It has no driver,
transport or device-write methods and is not wired into `main.py` or GPM.
`control_ready` is always false. This defines lifecycle/ownership behavior to
replay before a separately qualified timed-boost/release transport is introduced.
No existing hot-water override, hygiene rule, shadow setting or live writer changes.

An explicit proposal (start/end/deadline), Celsius target, electrical-cycle maximum
runtime, temperature age policy, transport and receipt acceptance policy are
required. Enabled local REST must use `nibe_local`; missing local measurements
never switch the evaluator to cloud. Fresh local-receipt evidence can be accepted
explicitly without relabelling it as a device source timestamp. Sensor roles and
these policy values still require installation qualification.

The evaluator accepts the original reserved start only. Early ticks wait; a missed
start is cancelled instead of silently extending the load reservation. A fresh
target already reached needs no simulated start. Active target completion needs
a fresh observation after the simulated start acknowledgement. Matching temperature
does not prove causality, hygiene completion or actual heater operation.

Each `would_start`/`would_release` is persisted as pending before being returned,
with an opaque acknowledgement token. Repeated ticks never repeat it. A caller
must explicitly acknowledge a **simulated** accepted/rejected/uncertain result.
Unknown, rejected, stale-token or missing acknowledgements never become success.
The simulation acknowledgement window is 60 seconds; this is not a hardware timeout
recommendation. Runtime/end-of-reservation, cancellation, guard loss or loss of
temperature freshness propose release once. Only a target-driven release followed
by accepted simulated acknowledgement is marked complete; other stops are cancelled.

Manual/away/hygiene precedence or leaving shadow mode interrupts the simulation
without proposing cleanup against another owner's settings. Clock rollback also
interrupts it. Restart never resumes stored pending/active authority: the journal
is replaced by an interrupted/reconciliation-required marker. No real recovery
or automatic physical cleanup is claimed; future real control needs independent
ownership/readback reconciliation and a qualified release path.

`open_journal(path)` uses an explicit private single-owner local file, an atomic
replacement and file flush/fsync. Persistence failure prevents proposals. It is
not a multi-process actuator lock or a power-loss durability guarantee. No default
runtime path is used. Only code-owned transport labels and bounded cycle values
are stored; no endpoints, parameter IDs, credentials or raw device responses.
Starting another simulation requires a new journal or an explicit operator-managed
reset, never an automatic retry of an interrupted cycle.

Replay frozen inputs using:

```text
python scripts/replay_hot_water_cycle.py replay.json --journal private/cycle.json
```

JSON contains `proposal` (as produced by the offline scheduler), `policy` (the
explicit `arm` arguments, with epoch-second `now`), and `events`. Each event is
`{"kind":"tick","inputs":{...}}` or
`{"kind":"acknowledge","inputs":{"outcome":"accepted","now":...}}`.
Ticks require epoch `now`, `shadow`, `permitted` and a normalized temperature
`observation`; manual/away/hygiene/cancel flags are optional. Acknowledgements are
simulation inputs, not transport receipts. Input is limited to 2 MB/1000 events.
The CLI only reads that input and writes the explicitly named simulation journal.

Remaining #407 work: actual runtime scheduling, comfort/deadline policy, qualified
temperature roles and transport start/release semantics, ongoing-cycle/readback
reconciliation, idempotent residual-baseline reservations, UI visibility and field
verification. This milestone must not be connected directly to actuator calls.
