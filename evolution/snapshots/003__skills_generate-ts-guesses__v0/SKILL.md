---
name: generate-ts-guesses
description: Generates or corrects transition state (TS) guess structures for the ReactionAgent workflow. Inputs include record.json, reactant/product SMILES, atom mapping information, 3D structures of reactants, and historical failure diagnosis feedback. Outputs multiple TS guess .xyz files for the current round and updates the current block of record.json via tools/record_update.py.
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



# Generate TS Guesses

## Purpose

This skill generates transition state (TS) guess structures for a reaction.

Inputs include:
- Reactant SMILES
- Product SMILES
- Reactant 3D structure
- Atom-mapped reaction center
- Optional: diagnostic feedback from a previous ORCA/xTB failure

Outputs include:
- Several TS guess `.xyz` structures
- A `round_N/guesses.record_update.json` fragment file
- A call to `tools/record_update.py` to write the guesses into the current round block in `record.json`

Generation strategy:
- The initial round should cover multiple plausible mechanisms or conformational directions.
- Each mechanism usually generates three TS guess types: early, middle, and late.
- Revision rounds should generate structures based on `diagnosis_feedback`: if `if_need_new_mechanism = false`, modify the old structure according to the failure reason; if `if_need_new_mechanism = true`, abandon the corresponding failed mechanism, propose a new mechanistic hypothesis, and generate new TS guesses instead of stopping the task.
- Each guess must record the actually measured key geometric parameters, not only the target values.

## Procedure

1. Read the input
   - Read `record.json`; it is an array, and each element represents one round.
   - The last array element, `record[-1]`, is the current round to generate.
   - Infer the current round number from the list index; it is not written in the JSON.
   - If the current round index is 0, handle it as initial generation.
   - If the current round index is greater than 0, read `guesses` and `diagnosis_feedback` from all previous blocks and handle it as revision generation.
   - Do not inspect only the previous round; all historical feedback after multiple iterations must be used as context.
   - If a historical feedback entry marks a mechanism with `branch_decision = stop_this_branch` and `if_need_new_mechanism = true`, this only means the old branch should be stopped; the current round should generate a different new mechanism or conformational strategy.

2. Understand the reaction center
   - **TS guesses must be generated strictly according to the `formed_bonds` and `broken_bonds` fields in `reaction_mapping.json`.**
   - Do not infer the mechanism from SMILES or chemical intuition on your own; the mapping information is authoritative.
   - First use `tools/inquire.py` to query the distances of atom pairs in `formed_bonds` in the reactant and confirm whether they are already bonded in the reactant.
   - Identify the bonds to be formed, bonds to be broken, proton-transfer sites, key angles, and key dihedrals.
   - Infer which bonds are spectator bonds and keep them reasonable while generating structures.

3. Query the reactant geometry
   - Use `tools/inquire.py` to query key bond lengths, bond angles, and dihedral angles.
   - Use these values as the baseline for designing TS guesses.

4. Design TS guesses
   - Set forming bonds to longer distances that still indicate an interaction.
   - Set breaking bonds to elongated distances.
   - For proton transfer, elongate the donor-H bond and shorten the H-acceptor distance.
   - Adjust angles or dihedrals as required by the mechanism so that bond-forming and bond-breaking directions are reasonable.
   - For each guess, clearly describe the mechanism, stage, and key geometry targets it represents.

5. Build structures
   - Use `tools/builder.py` to modify the reactant structure step by step.
   - Each builder call must perform only one bond, angle, or dihedral operation.
   - The `.xyz` output from the previous step must be used as the input for the next step.
   - Do not stack multiple geometry operations in a single builder command.

6. Validate structures
   - For every generated `.xyz`, use `tools/inquire.py` to query the actual geometry values.
   - Also check key spectator bonds or retained fragments to avoid corrupting the structure.
   - Record actual measured values in `generator_notes`, not the target values from builder commands.
   - `generator_notes` must include a sanity-check conclusion, such as `sanity_check=passed`, or explain why the structure was rejected and rebuilt.

7. Write to record
   - Do not manually edit or rewrite the complete `record.json`.
   - Write the current round's guesses list to `round_N/guesses.record_update.json`.
   - Use `tools/record_update.py` to copy that fragment into the current round block.

## `tools/builder.py` Usage

`builder.py` uses ASE to modify internal coordinates in a GaussianView-style workflow.

Basic format:

```bash
python tools/builder.py input.xyz output.xyz [operation]
```

Use 1-based atom indices.

### Modify Bond Length

```bash
python tools/builder.py in.xyz out.xyz \
  --bond I J VALUE MODE_I MODE_J
```

- `I J`: the two atom indices
- `VALUE`: target bond length in Angstrom
- `MODE_I MODE_J`: how the two ends are moved
- Available modes: `fixed`, `translate-group`, `translate-atom`

Example:

```bash
python tools/builder.py step0.xyz step1.xyz \
  --bond 2 7 2.10 fixed translate-group
```

Meaning: keep the side containing atom 2 fixed, move the fragment containing atom 7, and adjust the 2-7 distance to 2.10 Angstrom.

### Modify Bond Angle

```bash
python tools/builder.py in.xyz out.xyz \
  --angle I J K VALUE MODE_I MODE_J MODE_K
```

- `I J K`: angle `I-J-K`
- `VALUE`: target angle in degrees, from 0 to 180
- Available modes for endpoints `I/K`: `fixed`, `rotate-group`, `rotate-atom`, `translate-group`
- Available modes for center `J`: `fixed`, `translate-group`, `translate-atom`

Example:

```bash
python tools/builder.py step1.xyz step2.xyz \
  --angle 2 7 9 112 fixed fixed rotate-group
```

### Modify Dihedral Angle

```bash
python tools/builder.py in.xyz out.xyz \
  --dihedral I J K L VALUE MODE_I MODE_L
```

- `I J K L`: dihedral angle `I-J-K-L`
- `VALUE`: target dihedral angle in degrees, from -180 to 180
- Available modes: `fixed`, `rotate-groups`, `rotate-group`, `rotate-atom`

Example:

```bash
python tools/builder.py step2.xyz final.xyz \
  --dihedral 1 2 7 9 -60 fixed rotate-group
```

### Important Rules

Do not do this:

```bash
python tools/builder.py reactant.xyz guess.xyz \
  --bond 2 7 2.10 fixed translate-group \
  --angle 2 7 9 112 fixed fixed rotate-group
```

Although the tool supports executing multiple operations in sequence, this workflow requires one command per operation so that it is easy to identify which step damaged the structure.

After each builder call, perform a local check:
- Query whether the internal coordinate just modified reached the target.
- Query whether key internal coordinates already set in previous steps were disrupted.
- If an operation causes spectator bonds or intrafragment atom distances to become abnormally short, immediately rebuild with a different mode or operation order instead of continuing to stack later operations.

Common option:

```bash
--print-final
```

Print the final internal coordinate value requested by this operation.


## `tools/inquire.py` Usage

`inquire.py` is used to query bond lengths, bond angles, and dihedral angles in a structure. It can also compare them against a reference structure.

Basic format:

```bash
python tools/inquire.py structure.xyz [query]
```

Use 1-based atom indices.

### Single Query

Query a bond length:

```bash
python tools/inquire.py guess.xyz 2 7
```

Query a bond angle:

```bash
python tools/inquire.py guess.xyz 2 7 9
```

Query a dihedral angle:

```bash
python tools/inquire.py guess.xyz 1 2 7 9
```

### Batch Query

```bash
python tools/inquire.py guess.xyz \
  --bond 2 7 \
  --bond 4 8 \
  --angle 2 7 9 \
  --dihedral 1 2 7 9
```

### Compare with a Reference Structure

```bash
python tools/inquire.py guess.xyz \
  --reference reactant.xyz \
  --bond 2 7 \
  --angle 2 7 9
```

The output contains the current value, reference value, and difference.

### JSON Output

```bash
python tools/inquire.py guess.xyz \
  --bond 2 7 \
  --angle 2 7 9 \
  --json
```

## Output Format

Save TS guess structures to:

```text
round_N/guesses/{guess_id}.xyz
```

After generation, first write a guesses-list fragment file:

```json
[
  {
    "guess_id": "mech1_middle",
    "mechanism_id": "mech1",
    "mechanism_name": "concerted_or_stepwise_description",
    "mechanism_description": "Describe the bond-forming, bond-breaking, proton-transfer, or conformational hypothesis corresponding to this guess.",
    "ts_stage": "middle",
    "xyz_path": "round_N/guesses/mech1_middle.xyz",
    "generator_notes": "Record the actually measured key geometry values, for example C2-O7=2.08 A, O7-H12=1.25 A, H12-N9=1.35 A, angle C2-O7-H12=118.4 deg.",
    "validation": {
      "status": "pending",
      "failed_step": null,
      "failure_code": null,
      "failure_reason": null,
      "metrics": {},
      "files": {}
    }
  }
]
```

Then execute:

```bash
python tools/record_update.py set-guesses \
  --record workdir/record.json \
  --json-file workdir/round_N/guesses.record_update.json
```

`record.json` is the only state file passed through the workflow. Do not manually rewrite the complete `record.json`; writing must be performed by `tools/record_update.py`.

Field requirements:
- `guesses.record_update.json` must be a list, and each element must be a guess object.
- `tools/record_update.py` writes this list to `record[-1]["guesses"]`.
- Each round block in `record.json` may contain only three fields: `generation_policy`, `guesses`, and `diagnosis_feedback`.
- The next Generator must read the entire `record.json` array and integrate all historical `guesses` and `diagnosis_feedback`.
- `guess_id` must be unique; `{mechanism_id}_{stage}` is recommended.
- `xyz_path` should be relative to the workflow working directory.
- `generator_notes` must contain key geometry parameters actually measured by `inquire.py`.
- Newly generated guesses must always start with `validation.status` set to `pending`.
