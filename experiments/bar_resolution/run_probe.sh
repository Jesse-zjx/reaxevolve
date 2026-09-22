#!/usr/bin/env bash
# Bar-resolution negative control. Design and declared outcomes:
# preregistration/bar_resolution_probe.md — read it before reading a result from here.
#
# Reaches a deposited dry saddle by uniform linear interpolation, a method that cannot place the
# migrating hydrogen on the coordinate that matters, and submits the result to the unmodified
# acceptance path. Expected: rejection. A clean pass makes the control inconclusive, not the bar
# wrong.
#
#   bash experiments/bar_resolution/run_probe.sh
#
# Needs ORCA and xTB. Writes under runs/bar_resolution/ (gitignored); the verdict lands in a
# strict_cache.json there via the usual write entry, and nothing is added to Graph Memory
# because the probe edge is deliberately outside the panel and the C2 route.
set -uo pipefail

PKG="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${CHEM_PYTHON:-python3}"

R="O=C(CO)C(O)C(O)C(O)CO"          # keto  (FF deposit step 2 reactant)
P="OCC(O)=C(O)C(O)C(O)CO"          # enol  (FF deposit step 2 product)
NAME="bar_probe_ff_s2_interp"
NPROCS="${NPROCS:-16}"

STEP="$PKG/runs/bar_resolution/ff_s2"
mkdir -p "$STEP"
cd "$PKG"

echo "== 1. reactant geometry from SMILES =="
$PY tools/geometry/smi_to_xyz.py "$R" "$STEP/reactant.xyz" --name keto || exit 1

echo "== 2. step contract for the interpolation guesser =="
cat > "$STEP/yarp_route.json" <<JSON
{
  "reactant_smiles": "$R",
  "product_main_smiles": "$P",
  "product_balanced_smiles": "$P",
  "reaction_kind": "tautomerization",
  "note": "bar-resolution probe: guesses are deliberately naive; see preregistration/bar_resolution_probe.md"
}
JSON

echo "== 3. naive interpolation guesses (no reaction-coordinate reasoning) =="
$PY tools/guess/auto_guess.py --step-dir "$STEP" --round 0 --n-guesses 3 || exit 1
# The generator lays guesses out one per fraction directory, not in a flat guesses/ folder.
mapfile -t GUESSES < <(find "$STEP/round_0" -name 'guess.xyz' | sort)
[ "${#GUESSES[@]}" -gt 0 ] || { echo "no guesses produced"; exit 1; }
echo "  ${#GUESSES[@]} guesses: ${GUESSES[*]#$STEP/}"

echo "== 4. unmodified acceptance path, one guess at a time =="
i=0
for g in "${GUESSES[@]}"; do
  i=$((i+1))
  wd="$STEP/attempt_$i"
  mkdir -p "$wd"
  echo "-- guess $i: $(basename "$g")"
  $PY tools/workflow/run_qm_step.py \
      --name "${NAME}_g${i}" \
      --guess "$g" \
      --reactant "$R" \
      --product "$P" \
      --nprocs "$NPROCS" \
      --workdir "$wd" 2>&1 | tail -20
done

echo
echo "== verdicts =="
find "$STEP" -name 'strict_cache.json' -exec sh -c 'echo "--- $1"; cat "$1"' _ {} \;
