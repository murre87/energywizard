# Opt-in local hot-water runtime

The engine can explicitly opt into `hot_water_runtime.Runtime`, using the local
boost driver and bounded controller. Existing installations remain unchanged.
No live configuration or device command was applied while implementing this.

Synthetic configuration example, not installation defaults:

```yaml
heat_pump:
  enabled: true
  driver: nibe_local
  control_enabled: true
  # Existing qualified connection and explicit native points remain required.
  hot_water_control:
    enabled: false
    exclusive_owner_confirmed: false
    temperature_role_verified: false
    max_runtime_s: 1800
    comfort_policy:
      comfort_c: 40
      target_c: 55
      max_trigger_age_s: 151200
      min_trigger_interval_s: 86400
      comfort_window_s: 3600
      comfort_bypasses_interval: false
      duration_min: 30
      electrical_power_kw: 2.5
      max_age_s: 90
      allow_receipt: true
```

Exclusive ownership is an explicit installation handover acknowledgement; the
software cannot stop Zenai or discover every other writer. Global shadow still
blocks commands. Disabled/unqualified/unsupported installations start no worker,
query no prices and open no control journal. This opt-in is local REST only.

The engine ticks the controller each regular evaluation, after battery/EV grants.
Start permission requires fresh meter and phase-current evidence, conservative
headroom (all configured heating power could land on one phase), and available
current hourly peak budget. Pending ramp grants count against headroom; a boost
attempt also reserves the existing 90-second ramp budget for other loads. Active
heating is already in measured current and is not added again to its own guard.
These are current operational guards, not a forecast of future fuse/peak headroom
or a guarantee that delayed heat-pump electrical load follows the assumed power.
Regular monitoring, native protection and physical commissioning remain necessary.

Stored full import prices supply the existing contiguous-window planner. Demand
anchors and independently confirmed real trigger times persist across cycles.
Trigger age can exceed 36 hours (including the personal 42-hour setting); its
fixed deadline stays unchanged, while each price search covers at most the next
36 hours. Missing prices do not force an immediate start or move the anchor.
No battery forecast reservation is injected: the existing household baseline may
already include hot water. No dedicated heater electrical meter is required here.

When selected, the runtime replaces normal quarter-hour water-setpoint writes,
including if its storage/configuration fails. Manual and hygiene precedence
retain the existing setpoint path, while invalidating boost authority without
issuing cleanup against another owner. Away/guard loss releases an owned boost.
Room-heating, summer-mode and other device paths remain unchanged; they must be
reviewed for the installation before handover. The old advisory shadow monitor
does not authorize or supply the real controller's state.

State lives in `hot-water-control.json` beside `energywizard.json`, mode 0600,
with atomic replacement, file/directory fsync and a lifetime Linux process lock.
Malformed/unreadable/context-mismatched journals block control rather than
becoming empty history. Connection/binding/policy values are hashed into context;
credentials and raw configuration are not written to this journal or status.
The owner Settings page has a read-only hot-water control status card in Swedish,
English and Czech. `GET /api/hot-water-control-status` requires owner access before
configuration or database reads. The engine publishes only allowlisted state and
window timestamps; errors, credentials, context hashes and raw reasons stay private.
Reports expire after 90 seconds, including failed publication or a stopped engine.
Publication uses one worker and one waiting report, replacing older waiting reports;
database latency cannot block the control loop or accumulate an unbounded queue.
The card has no start, release, recovery or configuration buttons.

After restart, never-attempted plans may be replanned using the persisted demand
anchor. Active/pending commands require operator recovery; retained configuration
does not automatically reconfirm their ownership. Interrupted authority is also
blocked. Do not delete a journal merely to clear these states: first stop other
writers, reconcile any in-flight command and independently verify the heater is
released through the qualified local mapping.

With EW stopped and exclusive ownership verified, the operator can run:
Use a repository checkout with access to the same data volume and the same
`NIBE_LOCAL_*` environment as EW; the repository script is not copied into the
engine image. Do not substitute a different heater endpoint or journal.

```sh
python scripts/recover_hot_water.py --config /data/house_config.yaml \
  --journal /data/hot-water-control.json \
  --confirm-exclusive-ownership --confirm-pending-commands-settled
```

The tool constructs a read-only local driver, takes the same exclusive journal
lock, checks context/history/clock and requires independent released readback.
Context includes the driver's resolved local host, port and device selector,
including an address supplied through the environment.
It sends no heater commands, never replays a pending start/release and refuses
active/unknown states. Pending commands must be settled by the operator first:
one released read cannot prove a delayed command will never arrive. Do not pass
the confirmations until that reconciliation has happened.

Recovery preserves the demand anchor and known real trigger history and retains
the old cycle as `recovered_cycle`; it clears only current cycle authority. It
does not claim an unconfirmed start succeeded or move an overdue deadline. EW can
then restart and plan using that retained history. Changed context, malformed
state or invalid clocks require separate review, not an automatic reset.
Personal live commissioning remains outstanding; this tool was tested only with
synthetic heater transport and private temporary journals.
Storage failures, process downtime and transport outages cannot guarantee release.
