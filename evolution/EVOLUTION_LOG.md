# Evolution log

Machine record: `EVOLUTION_LOG.jsonl` (append-only, one entry per revision).
Asset name changes across the two asset sets: `ASSET_RENAMES.json`.

Revisions are ordered by `seq` and versioned per asset. There are no wall-clock
timestamps: what has to be checkable is the order of revisions, the evidence that
triggered each one, and the pre-change snapshot it can be diffed against.

`class` distinguishes revisions driven by recorded QM failures (`qm_feedback`) from
path/format fixes (`plumbing`) and from renames and splits of the asset surface
(`reorganization`). Only `qm_feedback` entries carry a claim about capability.

Entries: **58** — qm_feedback 50, plumbing 7, reorganization 1

## Revisions per asset

| Asset | Revisions | Final version |
|---|---|---|
| `.skills/` | 1 | — |
| `.skills/diagnose-ts-failures` | 6 | v6 |
| `.skills/generate-ts-guesses` | 42 | v42 |
| `.skills/qm-execution` | 3 | v3 |
| `tools/expand/templates_expand.py` | 2 | v2 |
| `tools/guess/` | 1 | v1 |
| `tools/guess/scan2d_guess.py` | 1 | v1 |
| `tools/screen/diversity.py` | 1 | v1 |
| `tools/workflow/soft_mode_cleanup.py` | 1 | v1 |

## Triggering failure modes

| Failure mode | Revisions |
|---|---|
| `no_dominant_mode` | 34 |
| `no_endpoint_record` | 6 |
| `no_endpoint_record / no_dominant_mode` | 4 |
| `no_endpoint_record and no_dominant_mode` | 2 |
| `no_match` | 2 |
| `path_alias` | 1 |
| `no_endpoint_record (dominant across isomerization, unattributed, dehydrogenation)` | 1 |
| `no_dominant_mode and no_endpoint_record` | 1 |
| `multi-kind: no_endpoint_record + no_dominant_mode` | 1 |
| `no_dominant_mode (soft modes in TS optimization, guesses not crossing reaction coordinate)` | 1 |
| `no_dominant_mode, no_endpoint_record` | 1 |
| `multiple_imaginary` | 1 |
| `low_candidate_yield` | 1 |
| `near_duplicate_spend` | 1 |
| `-` | 1 |

## Entries

- `001` **.skills/qm-execution** v0→v1 [qm_feedback]
  - failure mode: `no_endpoint_record`
  - intended effect: Reduce 'no_endpoint_record' failures by ensuring IRC endpoints are recorded before proceeding to verdict; expected to increase pass rate and enable more STRICT edges.
  - snapshot: `evolution/snapshots/001__skills_qm-execution__v0`
- `002` **.skills/qm-execution** v1→v2 [plumbing]
  - failure mode: `path_alias`
  - intended effect: verify skills/→.skills/ apply lands
  - snapshot: `evolution/snapshots/002__skills_qm-execution__v1`
- `003` **.skills/generate-ts-guesses** v0→v1 [plumbing]
  - failure mode: `no_endpoint_record (dominant across isomerization, unattributed, dehydrogenation)`
  - intended effect: Reduce the number of guess attempts with no endpoint record by at least 50% in the next Validate round, by generating fewer, higher-quality TS guesses that are constrained to yield clear IRC paths. This should increase the proportion of STRICT edges from validated calculations.
  - snapshot: `evolution/snapshots/003__skills_generate-ts-guesses__v0`
- `004` **.skills/diagnose-ts-failures** v0→v1 [qm_feedback]
  - failure mode: `no_endpoint_record`
  - intended effect: Reduce IRC endpoint record failures by giving explicit re-guess strategy, leading to more successful IRC endpoints and increasing chance of STRICT edges.
  - snapshot: `evolution/snapshots/004__skills_diagnose-ts-failures__v0`
- `005` **.skills/generate-ts-guesses** v1→v2 [qm_feedback]
  - failure mode: `no_endpoint_record`
  - intended effect: Reduce the rate of 'no_endpoint_record' failures by 50% or more in the next Validate round, increasing the number of validated edges and potentially adding STRICT edges.
  - snapshot: `evolution/snapshots/005__skills_generate-ts-guesses__v1`
- `006` **.skills/diagnose-ts-failures** v1→v2 [qm_feedback]
  - failure mode: `no_endpoint_record`
  - intended effect: Reduce the 'no_endpoint_record' failure rate by providing actionable diagnosis, leading to more successful IRC endpoint records and potentially more STRICT edges.
  - snapshot: `evolution/snapshots/006__skills_diagnose-ts-failures__v1`
- `007` **.skills/diagnose-ts-failures** v2→v3 [qm_feedback]
  - failure mode: `no_endpoint_record and no_dominant_mode`
  - intended effect: Next Validate round will have more specific recovery actions for missing endpoints and soft modes, leading to fewer repeated failures and potentially new STRICT edges.
  - snapshot: `evolution/snapshots/007__skills_diagnose-ts-failures__v2`
- `008` **.skills/generate-ts-guesses** v2→v3 [plumbing]
  - failure mode: `no_dominant_mode and no_endpoint_record`
  - intended effect: Reduce the rate of unattributed and no_endpoint_record failures by ensuring TS guesses have a single dominant imaginary frequency, leading to higher IRC completion rates and more validated TS edges, ultimately increasing d_strict.
  - snapshot: `evolution/snapshots/008__skills_generate-ts-guesses__v2`
- `009` **.skills/generate-ts-guesses** v3→v4 [qm_feedback]
  - failure mode: `no_endpoint_record / no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that yield no IRC endpoint record or only soft modes. Expect more guesses to produce at least one endpoint match, increasing the chance of a STRICT edge from Validate.
  - snapshot: `evolution/snapshots/009__skills_generate-ts-guesses__v3`
- `010` **.skills/diagnose-ts-failures** v3→v4 [qm_feedback]
  - failure mode: `no_endpoint_record and no_dominant_mode`
  - intended effect: Reduce no_endpoint_record failures by re-running IRC with robust settings; reduce soft-mode no_dominant_mode failures by perturbing along the imaginary mode vector; increase the rate of IRC endpoint records and valid TS matches, ultimately leading to more STRICT edges.
  - snapshot: `evolution/snapshots/010__skills_diagnose-ts-failures__v3`
- `011` **.skills/generate-ts-guesses** v4→v5 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the number of submitted guesses, increase the fraction with a single dominant imaginary mode, and thereby raise the probability of successful IRC and endpoint recording, leading to more STRICT edges.
  - snapshot: `evolution/snapshots/011__skills_generate-ts-guesses__v4`
- `012` **.skills/diagnose-ts-failures** v4→v5 [qm_feedback]
  - failure mode: `no_endpoint_record`
  - intended effect: Reduce the number of no_endpoint_record failures by providing concrete next-guess instructions, leading to more successful IRC endpoints and thus more potential STRICT edges.
  - snapshot: `evolution/snapshots/012__skills_diagnose-ts-failures__v4`
- `013` **.skills/qm-execution** v2→v3 [qm_feedback]
  - failure mode: `no_endpoint_record`
  - intended effect: Reduce the rate of no_endpoint_record failures from ~40% to near 0% by verifying IRC endpoints after each run and re-running with longer IRC paths if missing, thereby increasing the chance of STRICT edge validation.
  - snapshot: `evolution/snapshots/013__skills_qm-execution__v2`
- `014` **.skills/generate-ts-guesses** v5→v6 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of guesses that lack a genuine saddle point (no dominant imaginary mode). Expect more TS guesses to pass IRC and yield endpoint records, increasing the success rate of Validate rounds and eventually adding new STRICT edges.
  - snapshot: `evolution/snapshots/014__skills_generate-ts-guesses__v5`
- `015` **.skills/generate-ts-guesses** v6→v7 [qm_feedback]
  - failure mode: `no_endpoint_record / no_dominant_mode`
  - intended effect: Next Validate round will see a higher fraction of TS guesses yielding a single dominant imaginary mode and successfully completing IRC to both endpoints, reducing the dominant failure modes and increasing the chance of new STRICT edges
  - snapshot: `evolution/snapshots/015__skills_generate-ts-guesses__v6`
- `016` **.skills/generate-ts-guesses** v7→v8 [qm_feedback]
  - failure mode: `no_endpoint_record / no_dominant_mode`
  - intended effect: Reduce failed attempts by generating fewer, higher-quality guesses that focus on early-path reactions and single-imag modes, leading to increase in STRICT edges in next Validate round.
  - snapshot: `evolution/snapshots/016__skills_generate-ts-guesses__v7`
- `017` **.skills/generate-ts-guesses** v8→v9 [qm_feedback]
  - failure mode: `multi-kind: no_endpoint_record + no_dominant_mode`
  - intended effect: Reduce the number of TS guesses per edge from up to 5 to max 2, focusing on chemically plausible mechanisms for dehydration and tautomerization. Expect fewer failed attempts with no_dominant_mode and no_endpoint_record, and increase the chance of STRICT edges in the next Validate round.
  - snapshot: `evolution/snapshots/017__skills_generate-ts-guesses__v8`
- `018` **.skills/generate-ts-guesses** v9→v10 [qm_feedback]
  - failure mode: `no_endpoint_record / no_dominant_mode`
  - intended effect: Increase the proportion of guesses that yield a single dominant imaginary mode and successful IRC endpoint records, thereby increasing the chance of new STRICT edges.
  - snapshot: `evolution/snapshots/018__skills_generate-ts-guesses__v9`
- `019` **.skills/generate-ts-guesses** v10→v11 [plumbing]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce no_dominant_mode failures by ensuring TS guesses have a single significant imaginary mode (>200 cm⁻¹) and correct endpoint matching. This will increase validation pass rate for isomerization/tautomerization edges, leading to more STRICT edges and faster progress toward HMF.
  - snapshot: `evolution/snapshots/019__skills_generate-ts-guesses__v10`
- `020` **.skills/generate-ts-guesses** v11→v12 [plumbing]
  - failure mode: `no_dominant_mode`
  - intended effect: Increase the fraction of TS guesses that yield a single imaginary frequency with dominant mode connecting reactant and product, and that produce valid IRC endpoints. Expect a measurable reduction in 'no_dominant_mode' and 'no_endpoint_record' failures in the next Validate round.
  - snapshot: `evolution/snapshots/020__skills_generate-ts-guesses__v11`
- `021` **.skills/generate-ts-guesses** v12→v13 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the number of no_dominant_mode failures for tautomerization guesses by at least 50% in the next Validate round, by ensuring that the initial guess places the migrating hydrogen at the donor-acceptor midpoint, which is expected to be closer to the saddle point.
  - snapshot: `evolution/snapshots/021__skills_generate-ts-guesses__v12`
- `022` **.skills/generate-ts-guesses** v13→v14 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that result in no_dominant_mode by providing geometries that are closer to the true saddle point. This should increase the number of successfully validated TS edges and potentially lead to new STRICT edges over the next few rounds.
  - snapshot: `evolution/snapshots/022__skills_generate-ts-guesses__v13`
- `023` **.skills/generate-ts-guesses** v14→v15 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that fail with no_dominant_mode (soft mode) by at least 50% in the next Validate round, enabling more valid TS and increasing chance of new STRICT edges.
  - snapshot: `evolution/snapshots/023__skills_generate-ts-guesses__v14`
- `024` **.skills/generate-ts-guesses** v15→v16 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that yield no_dominant_mode from ~50% to <25% in the next Validate round, increasing the number of valid saddle points and enabling IRC endpoint analysis.
  - snapshot: `evolution/snapshots/024__skills_generate-ts-guesses__v15`
- `025` **.skills/generate-ts-guesses** v16→v17 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that result in no_dominant_mode by providing chemical intuition guidelines and explicit failure-learning instructions. This should increase the number of validated guesses and eventually raise the number of STRICT edges.
  - snapshot: `evolution/snapshots/025__skills_generate-ts-guesses__v16`
- `026` **.skills/generate-ts-guesses** v17→v18 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that are soft minima or have multiple imaginary modes, leading to more valid TS optimizations and IRC endpoints, thus increasing the chance of new STRICT edges.
  - snapshot: `evolution/snapshots/026__skills_generate-ts-guesses__v17`
- `027` **.skills/generate-ts-guesses** v18→v19 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of guesses that converge to minima instead of true transition states. Expect higher proportion of TS candidates with exactly one imaginary frequency, leading to more validated edges and potentially new STRICT edges in the next Validate round.
  - snapshot: `evolution/snapshots/027__skills_generate-ts-guesses__v18`
- `028` **.skills/generate-ts-guesses** v19→v20 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the rate of no_dominant_mode failures by providing tighter initial guesses for tautomerization and isomerization, thereby increasing the chance of validated edges and new STRICT edges.
  - snapshot: `evolution/snapshots/028__skills_generate-ts-guesses__v19`
- `029` **.skills/generate-ts-guesses** v20→v21 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the number of TS guesses that result in soft‑mode failures, especially for tautomerization and isomerization. The expected outcome is that more validated edges will pass the STRICT check (dominant imaginary mode, endpoint match) and the number of strict edges will increase, driving the reaction graph toward HMF.
  - snapshot: `evolution/snapshots/029__skills_generate-ts-guesses__v20`
- `030` **.skills/diagnose-ts-failures** v5→v6 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Validation will receive explicit guidance to regenerate guesses with larger displacement or different reaction kind when no_dominant_mode occurs, potentially reducing wasteful retries and increasing the chance of finding a true saddle.
  - snapshot: `evolution/snapshots/030__skills_diagnose-ts-failures__v5`
- `031` **.skills/generate-ts-guesses** v21→v22 [qm_feedback]
  - failure mode: `no_dominant_mode (soft modes in TS optimization, guesses not crossing reaction coordinate)`
  - intended effect: Reduce the no_dominant_mode failure rate for isomerization/tautomerization and unattributed edges by ensuring guesses are positioned away from local minima, with sufficient gradient norm and RMSD from endpoints, encouraging a single imaginary mode > 100 cm⁻¹.
  - snapshot: `evolution/snapshots/031__skills_generate-ts-guesses__v21`
- `032` **.skills/generate-ts-guesses** v22→v23 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses rejected due to no_dominant_mode by at least 30% in the next Validate round.
  - snapshot: `evolution/snapshots/032__skills_generate-ts-guesses__v22`
- `033` **.skills/generate-ts-guesses** v23→v24 [plumbing]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce soft-mode guesses for tautomerization and isomerization reactions, leading to a higher proportion of TS guesses with a dominant imaginary mode and correct endpoint matching, thereby increasing the chance of new STRICT edges.
  - snapshot: `evolution/snapshots/033__skills_generate-ts-guesses__v23`
- `034` **.skills/generate-ts-guesses** v24→v25 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the rate of 'no_dominant_mode' failures by generating fewer, better-staged guesses that are more likely to possess a single imaginary frequency > 100 cm⁻¹. Expect an increase in validated_n per round (e.g., from 2 to 3-4) and a higher chance of new STRICT edges in the next 3 rounds.
  - snapshot: `evolution/snapshots/034__skills_generate-ts-guesses__v24`
- `035` **.skills/generate-ts-guesses** v25→v26 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of guesses with soft modes or multiple imaginary frequencies; increase the number of genuine TS with a single imaginary mode, leading to more successful IRC and STRICT edges in subsequent Validate rounds.
  - snapshot: `evolution/snapshots/035__skills_generate-ts-guesses__v25`
- `036` **.skills/generate-ts-guesses** v26→v27 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the proportion of TS guesses that fail with 'no_dominant_mode' by at least 30% in the next Validate round, increasing the validated TS count and thus the chance of new STRICT edges.
  - snapshot: `evolution/snapshots/036__skills_generate-ts-guesses__v26`
- `037` **.skills/generate-ts-guesses** v27→v28 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the rate of no_dominant_mode failures for tautomerization/isomerization edges by at least 30%, leading to more validated TS proposals and eventually new STRICT edges.
  - snapshot: `evolution/snapshots/037__skills_generate-ts-guesses__v27`
- `038` **.skills/generate-ts-guesses** v28→v29 [qm_feedback]
  - failure mode: `no_dominant_mode, no_endpoint_record`
  - intended effect: Increase the fraction of guesses that yield a single dominant imaginary mode and complete IRC endpoints, thereby raising the validation pass rate for isomerization, tautomerization, dehydrogenation, and dehydration.
  - snapshot: `evolution/snapshots/038__skills_generate-ts-guesses__v28`
- `039` **.skills/generate-ts-guesses** v29→v30 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of soft-mode TS guesses (imaginary frequency < 300 cm⁻¹) by 50%, increasing the pass rate for isomerization/tautomerization from 26/72 to >40/72 in the next 5 rounds, leading to more STRICT edges.
  - snapshot: `evolution/snapshots/039__skills_generate-ts-guesses__v29`
- `040` **.skills/generate-ts-guesses** v30→v31 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the number of isomerization/tautomerization TS guesses that result in soft modes (no_dominant_mode) by ensuring only chemically meaningful guesses are proposed. Expect a measurable increase in successful TS validation (endpoint record, dominant mode) and an increase in STRICT edges for this reaction kind.
  - snapshot: `evolution/snapshots/040__skills_generate-ts-guesses__v30`
- `041` **.skills/generate-ts-guesses** v31→v32 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that result in soft modes (no_dominant_mode) and no_endpoint_record, increasing validation pass rate for isomerization/tautomerization and dehydration, thereby enabling new STRICT edges and progress toward HMF.
  - snapshot: `evolution/snapshots/041__skills_generate-ts-guesses__v31`
- `042` **.skills/generate-ts-guesses** v32→v33 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Increase the fraction of TS guesses for isomerization/tautomerization that exhibit a dominant imaginary frequency (>|300| cm-1), leading to more successful IRC endpoint matching and fewer rejected TS attempts.
  - snapshot: `evolution/snapshots/042__skills_generate-ts-guesses__v32`
- `043` **.skills/generate-ts-guesses** v33→v34 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Increase TS guess quality: reduce soft-mode failures and no-endpoint-record failures, raising pass rate from 26/108 (24%) to >40% in the next Validate round, and enabling more STRICT edges.
  - snapshot: `evolution/snapshots/043__skills_generate-ts-guesses__v33`
- `044` **.skills/generate-ts-guesses** v34→v35 [plumbing]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of soft-mode failures by at least 30%, leading to more TS optimizations with a single dominant imaginary frequency and correct endpoint connectivity, thereby increasing the probability of new STRICT edges.
  - snapshot: `evolution/snapshots/044__skills_generate-ts-guesses__v34`
- `045` **.skills/generate-ts-guesses** v35→v36 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce no_dominant_mode failures by at least 30% over the next 5 rounds, increasing the yield of valid TS guesses that lead to IRC endpoints and STRICT edges.
  - snapshot: `evolution/snapshots/045__skills_generate-ts-guesses__v35`
- `046` **.skills/generate-ts-guesses** v36→v37 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the number of guesses that result in only soft imaginary frequencies; increase the proportion of true TS saddles found from isomerization/tautomerization guesses, thereby improving STRICT edge yield.
  - snapshot: `evolution/snapshots/046__skills_generate-ts-guesses__v36`
- `047` **.skills/generate-ts-guesses** v37→v38 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce soft-mode failures by at least 50% in the next 2 validation rounds, leading to a new STRICT edge within 3 rounds.
  - snapshot: `evolution/snapshots/047__skills_generate-ts-guesses__v37`
- `048` **.skills/generate-ts-guesses** v38→v39 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Sharply reduce the number of TS guesses that yield soft, multi‑imaginary modes. Expect a higher fraction of guesses to pass with a dominant mode and correct endpoint match, thereby increasing the chance of successful validation and STRICT edges.
  - snapshot: `evolution/snapshots/048__skills_generate-ts-guesses__v38`
- `049` **.skills/generate-ts-guesses** v39→v40 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of TS guesses that yield a soft imaginary mode (no_dominant_mode) from ~50% to under 20%, especially for isomerization/tautomerization. This should increase the number of validated TS edges, potentially adding new STRICT edges toward HMF.
  - snapshot: `evolution/snapshots/049__skills_generate-ts-guesses__v39`
- `050` **.skills/generate-ts-guesses** v40→v41 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of no_dominant_mode failures in TS guesses, increasing the chance of finding a proper saddle point with a large imaginary frequency, leading to more STRICT validations.
  - snapshot: `evolution/snapshots/050__skills_generate-ts-guesses__v40`
- `051` **.skills/generate-ts-guesses** v41→v42 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Reduce the fraction of guesses that produce soft modes (< 200 cm⁻¹) from ~30% to < 15%, thereby increasing the number of guesses that pass the STRICT criteria for dominant imaginary mode and endpoint matching, ultimately leading to new STRICT edges.
  - snapshot: `evolution/snapshots/051__skills_generate-ts-guesses__v41`
- `052` **tools/workflow/soft_mode_cleanup.py** v0→v1 [qm_feedback]
  - failure mode: `multiple_imaginary`
  - intended effect: Stop reporting a tool crash as a chemical negative. A rejected ORCA keyword made all candidates fail in under a second while the script printed 'no displacement gave a single imaginary mode'. After the fix a run with no frequency block reports RUN FAILED with the ORCA error attached and exits non-zero, so cleanup failures stop entering the record as evidence about the transition state.
- `053` **tools/guess/scan2d_guess.py** v0→v1 [qm_feedback]
  - failure mode: `no_match`
  - intended effect: Restore a guess generator for the one reaction kind that needs two coupled hydrogen migrations, which single-coordinate scans cannot reach. Rebuilt as a GFN2-xTB dual-distance constrained grid over the two migrating H located by atom mapping, handing the highest-energy point to the existing validator.
- `054` **tools/expand/templates_expand.py** →v1 [qm_feedback]
  - failure mode: `low_candidate_yield`
  - intended effect: Give Explore a deterministic, atom-conserving enumerator over the confirmed frontier: four reaction SMARTS (beta-elimination dehydration, keto<->enol 1,2-H shift, retro-aldol C-C cleavage) plus graph-based hemiketal ring close/open, with neutrality and implausible-motif filters. Broadens the queue without spending model tokens.
- `055` **tools/expand/templates_expand.py** v1→v2 [qm_feedback]
  - failure mode: `no_match`
  - intended effect: Rank the queue by which motifs actually clear the bar instead of by enumeration order: promote direct H-shift isomerization and beta-elimination that starts from an enol, demote the same elimination from a non-enol carbon and demote ring aromatization, prefer smaller reactants for DFT throughput, and add a distance-to-target term. Ordering only: status is still written solely by the verdict writer under policy/acceptance.
- `056` **tools/screen/diversity.py** →v1 [qm_feedback]
  - failure mode: `near_duplicate_spend`
  - intended effect: Add a novelty term against the already-known species set and fold it into the candidate score, so a batch spans distinct chemistry rather than variations of the best-scoring edge.
- `057` **tools/guess/** →v1 [qm_feedback]
  - failure mode: `no_dominant_mode`
  - intended effect: Replace one guess strategy with a per-reaction-kind set — constrained scan and dual scan for dehydration and C-C cleavage, dry proton transfer for keto<->enol, a 2D scan for two migrating hydrogens, NEB as a fallback — selected through a ladder keyed on reaction kind.
- `058` **.skills/** — [reorganization]
  - intended effect: Split and rename along those three concerns. Predecessor histories close at the versions below and the successors open at v1; the mapping is machine-readable in evolution/ASSET_RENAMES.json.
