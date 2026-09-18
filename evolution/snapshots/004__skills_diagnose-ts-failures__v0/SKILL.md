---
name: diagnose-ts-failures
description: Diagnose transition state (TS) validation failures from ORCA quantum chemistry calculations and write feedback into the current record.json block through tools/record_update.py. Use this skill when the user needs to analyze failed TS optimizations, understand why IRC endpoints don't match reactant/product, or generate recommendations for improving TS guesses.
---

## Genesis path map (chem-genesis)

All tool paths are relative to the chem-genesis workspace root:

| Skill path | Resolves to |
|---|---|
| `tools/builder.py` | `tools/geometry/builder.py` (shim) |
| `tools/inquire.py` | `tools/geometry/inquire.py` (shim) |
| `tools/map_reaction_atoms.py` | `tools/geometry/map_reaction_atoms.py` (shim) |
| `tools/parse_orca_output.py` | `tools/geometry/parse_orca_output.py` (shim) |
| `tools/xyz_to_smiles.py` | `tools/geometry/xyz_to_smiles.py` (shim) |
| `tools/record_update.py` | `tools/record_update.py` |
| `tools/workflow/run_qm_step.py` | stripped QM driver (OptTS+NumFreq+IRC → STRICT v5) |

Attempt scratch lives under `runs/validation/<step_id>/` (not TSBench benchmark dirs).
Do not read `workspaces/chem-discovery`, TSBench `benchmark/`/`results/`, or other agent transcripts.



# Diagnose TS Failures Skill

This skill diagnoses transition state (TS) validation failures and provides feedback for the next round of TS generation.

## When to Use This Skill

Use this skill when the user asks to:
- Diagnose why TS validation failed
- Analyze ORCA optimization results
- Understand IRC endpoint mismatches
- Generate feedback for next round of TS generation
- Work with `record.json` files

You can also invoke it directly:
```bash
/diagnose-ts-failures <record.json>
```

## What This Skill Does

1. Reads `record.json`
2. Analyzes ORCA output files and structures
3. Compares initial guess vs optimized TS geometry to identify trends
4. **Detects mechanism failures** (when 2+ guesses from same mechanism fail similarly)
5. Diagnoses each failed guess
6. Writes a feedback list fragment and uses `tools/record_update.py` to update the current record block

## Execution Workflow

Follow these steps in order:

### 1. Parse input JSON
- Read `record.json` from specified path
- Use `record[-1]` as the current round block
- Extract failed guesses and validation file paths from `record[-1]["guesses"]`

### 2. For each failed guess, gather evidence

a. **Check guess sanity before mechanism inference**:
   - Use `tools/inquire.py` on `guess.xyz` to check not only targeted forming/breaking coordinates, but also critical preserved bonds / fragment-internal bonds
   - If preserved connectivity is already corrupted in the initial guess, treat this as a guess-construction problem first
   - Do not conclude "reaction/pathway likely impossible" from guesses that are already chemically broken before ORCA meaningfully explores the PES

b. **Parse ORCA outputs** using `tools/parse_orca_output.py`:
   - OptTS: convergence status, final energy
   - NumFreq: imaginary frequency count and values
   - IRC: completion status
   - Endpoint opts: convergence status

c. **Query initial guess geometry** using `tools/inquire.py` on `guess.xyz`:
   - Key forming/breaking bond distances
   - Key preserved bond distances
   - Proton transfer distances if applicable
   - Critical angles/dihedrals

d. **Query optimized TS geometry** using `tools/inquire.py` on `ts_opt.xyz`:
   - Same parameters as initial guess
   - Calculate changes (Δ = optimized - initial)

e. **Check IRC endpoints** if available:
   - Use `tools/xyz_to_smiles.py` on raw IRC endpoints
   - Compare with reactant/product SMILES

f. **Analyze IRC trajectory** if available:
   - Use `tools/inquire.py` on `irc_IRC_Full_trj.xyz` to track key bond distances across frames
   - Check geometry evolution trends along the IRC path (e.g., forming bonds shortening, breaking bonds elongating)

### 3. Check for mechanism failure patterns

**CRITICAL**: Before diagnosing individual guesses, check if multiple guesses from the same mechanism show the same failure pattern.

**Common failure patterns:**
- Systematic dissociation (e.g., all show `C.C=C...` with methane leaving)
- Consistent wrong IRC endpoint
- Systematic H2 formation
- Consistent unexpected ring closure/opening

**If 2+ guesses from same mechanism show same pattern:**
- Read `references/mechanism_failure_detection.md` for detailed guidance
- Set `if_need_new_mechanism = true` in diagnosis

**If same mechanism failed in previous rounds:**
- Check previous blocks in `record.json`
- Compare prior `guesses` and `diagnosis_feedback`
- If same mechanism + similar pattern across rounds → abandon mechanism

### 4. Formulate diagnosis

For each failed guess:
- Determine `analysis_status` (see enums below)
- Decide `acceptance_verdict` and `branch_decision`
- Write clear diagnosis with geometry changes
- Generate specific numerical recommendations
- **Set `if_need_new_mechanism` flag appropriately**

### 5. Update record.json

- Populate `diagnosis_feedback` for each failed guess
- Do not manually edit or rewrite the full `record.json`
- Write the feedback list to `round_N/diagnosis_feedback.record_update.json`
- Run `tools/record_update.py` to copy that list into `record[-1]["diagnosis_feedback"]`
- Do not create `diagnostician_output.round_N.json`

## Tools to Use

**Primary tools**:
- `tools/parse_orca_output.py`: Parse ORCA output files
- `tools/inquire.py`: Query molecular geometry
- `tools/xyz_to_smiles.py`: Convert structures to SMILES

**Fallback tools** (only when primary tools insufficient):
- `grep`, `tail`, `cat`: For specific information

## Key Diagnostic Principles

### Geometry Change Analysis

When multiple guesses show same failure, compare initial vs optimized geometry:

1. Query initial guess: `python tools/inquire.py guess.xyz --bond 9 10 --json`
2. Query optimized TS: `python tools/inquire.py ts_opt.xyz --bond 9 10 --json`
3. Calculate Δ = optimized - initial
4. Interpret trends:
   - If forming bond shortens significantly → initial was too short, increase for next round
   - If proton fully transfers → correct TS has proton nearly transferred
   - If breaking bond elongates → initial was too short, increase for next round

### Guess Construction Sanity Check

Before declaring a mechanism failure, always ask:

1. Is the initial guess still chemically sane?
2. Are preserved fragment-internal bonds still near expected values?
3. Was the guess built through sequential single-coordinate edits, rather than stacked multi-edit builder commands?

If the initial guess is already broken:
- Diagnose the branch as a guess-construction / builder-strategy problem first
- Recommend rebuilding with sequential single-operation builder calls
- Do not use such guesses as primary evidence that the mechanism itself is wrong

### Mechanism Failure Detection

**When to set `if_need_new_mechanism = true`:**
- 2+ chemically sane guesses from same mechanism show same failure pattern
- Same mechanism failed across multiple rounds with similar patterns, and the failures are not explained by unphysical initial guesses or corrupted preserved bonds

**Read `references/mechanism_failure_detection.md` for:**
- Detailed detection rules
- How to question basic assumptions (proton transfer timing, bridging geometry, etc.)
- Diagnostic output requirements
- Examples of mechanism failures

### Asymmetric TS

Don't assume TS must be "symmetric" or "bridging". Many concerted reactions have asymmetric TS where one bond change leads another.

## Diagnostic Output Requirements

For each failed guess, output one `diagnosis_feedback` entry with:

- `guess_id`: Identifier
- `analysis_status`: See enums below
- `acceptance_verdict`: `accepted_ts`, `ts_candidate_only`, or `not_accepted`
- `branch_decision`: See enums below
- **`if_need_new_mechanism`**: Boolean (true if this failed mechanism should be abandoned and the Generator should try a different mechanism in the next round)
- `diagnosis`: Must include key geometry changes
- `tool_evidence_used`: Array of tool names
- `evidence`: Must include initial vs optimized geometry comparison
- `recommended_next_actions`: Based on optimization trends or mechanism change
- `suggested_builder_directions`: Specific numerical ranges
- `missing_information`: String or "none"
- `confidence`: `low`, `medium`, or `high`

### Enums

**analysis_status**:
- `job_crashed`, `optts_not_converged`, `converged_to_minimum`
- `multiple_imaginary_frequencies`, `one_imaginary_but_wrong_mode`
- `irc_failed`, `irc_one_branch_wrong`
- `ts_candidate_only`, `accepted_ts`, `ambiguous`

**branch_decision**:
- `continue_current_guess`, `continue_irc`, `continue_from_last_optimized_geometry`
- `revert_to_previous_guess`, `try_alternative_mechanism`
- `accept_final_ts`, `stop_this_branch`

`stop_this_branch` only stops the specific failed branch. If a different mechanism should still be explored, set `if_need_new_mechanism = true` and make `recommended_next_actions` describe the new mechanism direction.

### Content Requirements

**diagnosis**: One sentence summarizing cause, must include geometry changes

**evidence**: High-signal evidence only, must include initial vs optimized comparison

**recommended_next_actions**: 
- If `if_need_new_mechanism = false`: Geometry adjustments based on trends
- If `if_need_new_mechanism = true`: Recommend abandoning mechanism and trying fundamentally different approach
- If initial guess sanity is poor: explicitly recommend rebuilding the guess with sequential single-operation `builder.py` calls and preserved-bond checks

**suggested_builder_directions**: Specific numerical ranges with operation/atoms/target_range/mode/reason

## Endpoint Validation Strategy

When `failed_step == "endpoint_opt"` or `failure_code == "endpoint_smiles_mismatch"`:

1. Check IRC raw endpoints first: `python tools/xyz_to_smiles.py irc_IRC_F.xyz`
2. If raw endpoints match reactant/product: TS itself is valid
3. Also check partially optimized endpoints
4. Cross-validate: workflow uses endpoint opt SMILES

### Proton Transfer Diagnosis

If heavy-atom geometry looks reasonable but validation fails:
- Missing proton transfer
- Wrong proton donor/acceptor
- Relay mechanism not pre-organized

## Input/Output Formats

**Input:** `record.json`

**Output:** `round_N/diagnosis_feedback.record_update.json`, then updated `record.json`

The persistent multi-round record is `workdir/record.json`. Its format is:

```json
[
  {
    "generation_policy": {
      "mechanism_count": 2,
      "stages_per_mechanism": ["early", "late"]
    },
    "guesses": [],
    "diagnosis_feedback": []
  }
]
```

Each round's feedback belongs in that same round's `diagnosis_feedback` array, not in the next round block. Do not write the full `record.json` by hand; use:

```bash
python tools/record_update.py set-diagnosis-feedback \
  --record workdir/record.json \
  --json-file workdir/round_N/diagnosis_feedback.record_update.json
```

## Reference Files

- **`references/mechanism_failure_detection.md`** - Detailed guide on detecting and diagnosing mechanism failures. Read this when you detect 2+ similar failures from same mechanism.

## Error Handling

**If ORCA output files corrupted/missing:**
- Check `validation.files` paths
- Use fallback tools for partial information
- Set `confidence: "low"` and note in `missing_information`

**If key geometry parameters unclear:**
- Use `tools/inquire.py` systematically
- Check mapped SMILES for atom indices
- Set `missing_information` if critical info unavailable

**If the guess is already chemically broken before ORCA optimization:**
- State that preserved connectivity was not maintained
- Recommend fixing generator / builder strategy before drawing mechanism conclusions
- Lower confidence in any mechanistic interpretation derived from that branch

**If IRC endpoints ambiguous:**
- Always check raw IRC endpoints first
- Then check partially optimized endpoints
- Cross-validate with multiple SMILES conversions

## Invocation Examples

```bash
# Diagnose round 0 failures
/diagnose-ts-failures workdir/record.json
```

The skill writes `workdir/round_N/diagnosis_feedback.record_update.json`, then uses `tools/record_update.py` to update `workdir/record.json` in place.

## Top-Level Requirements

- Keep `record[-1]["guesses"]` unchanged except for reading evidence
- Generate a diagnosis feedback list for each failed guess
- Use `tools/record_update.py set-diagnosis-feedback` to write that list into `record[-1]["diagnosis_feedback"]`
- If successful guess already exists, `diagnosis_feedback` may be empty
- Do not create a next-round block; the controller handles appending to `record.json`
- Keep every record block limited to `generation_policy`, `guesses`, and `diagnosis_feedback`
