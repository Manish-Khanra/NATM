# Response to reviewer — maritime fleet fix and §4.5 corrections

*Audience: the paper authors and the reviewer. Contains ready-to-paste replacement text for `main.tex`, the corrected numbers, and a changelog of what was fixed in the model and the analysis notebook.*

This note addresses the four review points. Two are now fixed in code/results (1.10a, 1.10b); two are paper-text edits drafted below (1.11, cross-pathway demand).

---

## 1. Point 1.10a — maritime fleet expansion was a bug (FIXED)

### What was wrong
The model expanded the maritime fleet from 131 vessels to ~1,940–2,060 by 2030. This was **not a result**: one vessel (Cuxhavener Mineraloel GmbH) had an EU MRV/AIS-coverage artifact in its input activity — `annual_distance_km_base = 59.5 km/yr`, about 1,000× too low (the regional segment median is ~59,000 km/yr). Because each growth newbuild is templated from a representative existing vessel and copies its activity fields, and each regional operator owns a single vessel, that corrupt value became the growth template for its operator. Every newbuild was therefore credited ~1/1000 of the correct tonne-km capacity, and the capacity-based growth loop added ~1,800 phantom vessels to close the demand gap. These phantom vessels each sailed almost nothing (~30 MWh/yr vs a realistic ~120 GWh/yr), so they inflated the **vessel count and technology shares** while barely affecting delivered energy.

### The fix
A data-hygiene floor was added in the maritime fleet-stock loader (`navaero_transition_model/core/case_inputs/maritime_cargo_case.py`, `_floor_implausible_annual_distance`): any per-vessel `annual_distance_km_base` below 10% of its segment median is raised to that median, with a logged warning. It touches only vessel activity; **scenario tonne-km demand is untouched**. Four vessels are floored (Cuxhavener 59.5, Broring 570, Harry Stalzus 5,353 km regional; Hapag-Lloyd 6,110 km deep-sea).

### Corrected result (all 8 maritime cases re-run)
| Quantity | Before (buggy) | After (fixed) |
|---|---|---|
| Fleet 2030–2050 | ~1,940–2,060 | **239–241** (131 in 2025) |
| Energy per vessel | ~6 GWh/yr | **~52–66 GWh/yr** |
| 2050 technology (by delivered energy) | methanol 78%, ammonia 9% | **hybrid ~56%, LNG ~35%, biofuel ~4–9%**; methanol/ammonia not selected |
| Maritime electricity (direct charging) | — | ~1.4–1.9 TWh |

### Ready-to-paste replacement (maritime results, ~main.tex:1897–1905)
> The German cargo fleet of 131 vessels expands modestly to about 240 vessels by 2030 and then holds roughly constant to 2050, with the size near-identical across the eight behavioural cases (the demand anchor is met by renewal rather than large expansion). By 2050 the fleet decarbonises predominantly through **hybrid (battery-assisted diesel) propulsion (~56% of delivered energy), LNG dual-fuel (~35%), and drop-in biofuel (~4–9%)**; dedicated methanol and ammonia vessels are not selected under the current techno-economic assumptions. Reported by vessel count the shares are similar in ranking (hybrid and LNG dominant). Maritime electricity demand (grid-to-battery charging of the hybrid fleet) is about 1.4–1.9 TWh by 2050.

---

## 2. Point 1.10b — methanol/ammonia synthesis electricity (RESOLVED, with caveat)

The concern was that e-methanol/ammonia synthesis electricity is excluded from the accounting while those fuels dominate. After fixing 1.10a, **methanol and ammonia are no longer selected**, so the exclusion is immaterial to the corrected results: maritime electricity is grid-to-battery charging only, and it is fully accounted.

**Caveat to state in the paper (one line):** the electricity accounting attributes zero upstream electricity to methanol and ammonia carriers; this is immaterial here because those fuels are not chosen, but it means the method would understate electricity demand in any scenario that did select e-methanol/ammonia. A sensitivity note is recommended.

### Ready-to-paste caveat (energy-accounting methods, ~main.tex:2466–2469)
> Upstream (synthesis) electricity is attributed to e-kerosene (power-to-liquid) and to directly-charged or hybrid-electric assets; it is not attributed to methanol or ammonia carriers. In the present results this omission is immaterial, since dedicated methanol and ammonia vessels are not selected; it would, however, understate electricity demand in any scenario in which e-methanol or green ammonia is adopted at scale, which we flag as a sensitivity.

---

## 3. Point 1.11 — aviation fleet-share vs electricity (NOT a bug; reframe)

The numbers are internally consistent; the apparent inconsistency is a framing issue — an aircraft-**count** share compared against an energy-derived electricity figure, and a 2050 share compared against 2045 electricity.

**Reconciliation (Worst-case case, which carries the 16.31 TWh figure):**
- e-kerosene aircraft are **52.6%** of the fleet in **2045** (65.7% in 2050).
- Each e-kerosene aircraft burns a **realised 28% e-kerosene blend** (below the 45% catalog ceiling).
- So e-kerosene is **15.2% of fuel energy** in 2045 (19.3% in 2050): 7.74 TWh of fuel ÷ 0.48 PtL efficiency = **16.1 TWh electricity**, matching the reported value.

### Ready-to-paste reframing (aviation results, ~main.tex:1948–1951 and 2443–2446)
> Classified by aircraft count, SAF- and e-kerosene-compatible configurations reach 61–68% of the passenger fleet by 2050. By **fuel energy**, however, the synthetic (e-kerosene) share is smaller — about 15% in 2045 and 19% in 2050 — because each e-kerosene-configured aircraft operates at a realised ~28% synthetic blend, below the 45% blend ceiling. Passenger-aviation electricity demand follows the **fuel-energy** share (not the fleet-count share): at 7.7 TWh of e-kerosene fuel in 2045 and a 0.48 power-to-liquid efficiency, this is 16.3 TWh of electricity. Reporting is kept on an energy-share basis throughout to avoid conflating fleet composition with fuel composition.

*(Optional follow-up: investigate why the realised blend sits at 28% rather than the 45% ceiling — a mandate/availability cap — and state it. This is a modelling-choice question, not an inconsistency.)*

---

## 4. Transport demand identical across assessment pathways (justify)

NATM supplies one transport-demand vector per behavioural case and year, reused across the six assessment pathways (32 case–year rows → 192 case–pathway–year rows). Transport demand therefore has zero cross-pathway variance by construction.

### Ready-to-paste justification (coupling/methods, ~main.tex:936–941)
> The NATM transport demand is conditioned on the behavioural case — the actor's belief and decision rule already encode the transition pathway it responds to — and is then held fixed across the six assessment pathways, which vary only the electricity-system background. This isolates the power-system response to a given, belief-conditioned transport trajectory, rather than re-optimising transport against each assessment pathway. The consequence, which we state explicitly, is that transport contributes no cross-pathway variance to the coupled results: the reported spread in prices, redispatch and curtailment across assessment pathways is driven by the other sectors, with transport entering as a fixed, case-specific load.

---

## Changelog (what changed in the repository)

- **Model (code):** `navaero_transition_model/core/case_inputs/maritime_cargo_case.py` — added `_floor_implausible_annual_distance` (and a logged warning) in the fleet-stock normaliser. Applies to all maritime cases; no input CSV edited.
- **Results:** all 8 maritime cases re-run (`data/output/baseline-maritime-cargo-transition-*`, gitignored). Aviation cases unchanged (bug was maritime-only).
- **Analysis:** `analysis/section_4_5_fleet_fuel_electricity.ipynb` re-run against corrected data; stale maritime prose updated (fleet ~240 not 1,943–2,058; alt-share 0.68–0.82 not 0.96–0.98; LowDem-vs-Elec maritime diff +2 vessels not +115; technology story hybrid/LNG/biofuel not ammonia/methanol).
- **Not yet done (paper-text edits for the authors):** §3 (1.11 reframing), the maritime results paragraph, the two caveat/justification sentences above.
