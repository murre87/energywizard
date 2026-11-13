# hass-powerplan review — #214

Reviewed 2026-11-13: hass-powerplan
[`cfb1d36f6a44b60197d806d492db971cce54832b`](https://github.com/jkaberg/hass-powerplan/tree/cfb1d36f6a44b60197d806d492db971cce54832b)
against EnergyWizard `00f4d51`. Recommendation: independently extend price
provenance and constraint explanations in existing modules. Do not add a second
HA controller or replace our planning/control loop.

## Source findings

| Observed upstream design | Useful lesson | Existing EnergyWizard boundary |
| --- | --- | --- |
| Explicit price unit/currency normalization and source timezone. | A value needs provenance; negative price and unavailable price are distinct. | `nordpool.py`, `distribution_tariff.py`, price timezone/currency tests. |
| Forecast points have confidence; accessors can return unknown rather than zero. | Record quality before changing a consumer's fallback/dispatch policy. | `load_forecast_evaluation.py`, `ha_solar_forecast.py`, planning snapshots. |
| Allocation reports explain requested/reserved/granted/measured capacity and binding constraints. | Trace the actual restricting stage rather than infer a cause from low power. | `gpm.py`, `decision_summary.py`, `control_journal.py`, `ev_power.py`. |
| Counterfactual savings have confidence/calibration; site capacity cost is separately reported. | Keep observed cost, modeled savings and joint site fees distinct. | `plan_delivery.py`, `capacity_tariff.py`, #254/#257. |

Primary sources: [price normalization](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/core/pricing/normalise.py),
[forecast contract](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/core/forecasts/model.py),
[allocation report](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/core/allocation/report.py),
[savings](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/core/accounting/savings.py).
Source comments describe intended contracts; they are not independent evidence
of economic performance on our installations.

## Ranked independent proposals

1. **Price provenance and rejection explanations** — 1–2 days.
   Extend existing imported-slot diagnostics with source, declared units,
   currency/timezone, effective interval and fetch time. Keep the current
   conversions and fallback rules; unknown/mismatched data must be explicit.
   Test SEK/kWh versus minor units/MWh, negative prices, repeated/missing DST
   hours, refreshed future slots and protected completed history. Do not add
   implicit currency conversion or duplicate VAT/distribution charges.
2. **A constraint explanation record** — 1–2 days plus UI review.
   Trace requested current through each existing GPM/fuse/priority allocation
   stage into granted current, measurement and an optional binding reason.
   Reuse `decision_summary.py` and the journal. Missing phase/current data
   remains unknown; it must not turn into fictitious spare capacity. Test two
   cars, asymmetric phases, stale readings and no available current; EN/CS
   presentation and fuse decisions must remain unchanged unless separately
   specified. Coordinate the charger-evidence proposal in #199.
3. **Forecast-quality reporting** — 1–2 days.
   Attach sample count, age, coverage and the selected fallback to existing
   forecast comparison output. Distinguish a measured zero from missing input.
   Keep #257's chronological evaluation/adoption gate; do not import upstream
   confidence constants as calibrated EnergyWizard thresholds.

## What not to duplicate

The upstream [manifest](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/manifest.json)
defines an HA integration, not a standalone provider library. Its
[tariff catalogue](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/core/tariffs/__init__.py)
does not justify automatically adopting tariff values: country/provider coverage,
effective dates and bill semantics need independent verification. Keep our
existing configurable tariff engines and Swedish-source fallback boundary.

Its [radiator type](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/custom_components/powerplan/core/loads/types/radiator.py)
is useful context for #221, but multi-zone scheduling is broader than adding an
Adax manufacturer alias to a single heat-pump driver. Leave that integration
scope separate until its entity/control contract is available.

The pinned [LICENSE](https://github.com/jkaberg/hass-powerplan/blob/cfb1d36f6a44b60197d806d492db971cce54832b/LICENSE)
is MIT; no code was copied or new dependency installed. No HA/device execution,
shared-data benchmark or savings claim was made. This report completes the
requested research; the ranked implementation proposals are separate work.
