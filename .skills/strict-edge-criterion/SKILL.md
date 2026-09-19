---
name: strict-edge-criterion
description: >-
  Triage which candidate edges deserve QM before spending it — decides whether an
  elementary sugar/HMF step can be a STRICT neutral step (a single real TS whose raw
  IRC endpoints are exactly the neutral reactant and product), using validated
  motif classes and six proven not-strict-able classes. Skill
  pathway-method defines the bar itself and wins on any conflict. Use
  when planning/searching glucose→HMF (or any carbohydrate dehydration) routes,
  classifying candidate edges before spending QM, or building a reaction-network
  graph search for a fully-strict path.
---

# Strict-edge criterion (r2SCAN-3c/CPCM(water))

> Scope: this skill decides which edges are worth spending QM on. The acceptance bar itself is defined
> by skill `pathway-method` (HMF standard); where the two differ, that skill governs.

A step is STRICT-ABLE if and only if, at DFT, it has **exactly one** imaginary mode and the two raw IRC
ends are **exactly** the neutral reactant and the neutral product (RDKit canonical SMILES, charge = 0).

**When classifying a new candidate edge, do not plan on a spectator or catalytic water.** Under the rule
set by the expert after the furfural review, a new step whose IRC carries a standalone H₂O on *both*
endpoints is rejected: that water has no provenance in the chain and it breaks atom-count chaining. Water
should appear only as a genuine product of a real dehydration, i.e. on one side. (This governs new
candidates only; the accepted deposits stand as delivered.)

> Acceptance clauses: `policy/acceptance/STRICT.md` (v5). This skill does not redefine them.

## STRICT-ABLE motifs (validated, with the reason each works)
Every example below is an accepted step in one of the three expert-reviewed deposits; the tag gives the
route and step number so the imaginary frequency can be checked against
`<deposit>/04_orca_inp_out_hess/transition_states/`. Do not cite a motif here without that provenance.

1. Direct intramolecular tautomerization / isomerization (1,2- or 1,3-H shift), no water:
   - aldose↔ketose: open-glucose→open-fructose (−474.15, HAA s1; −434.65, FF s1)
   - keto↔enol: enol→3-deoxyglucosone (−1449.8, HMF s2); open-fructose→2,3-enediol (−2042.5, FF s2);
     2,3-enediol→3-ketohexose (−2032.5, FF s3); 3-deoxyxylosone (−2137.8, FF s8)
   - enediol→ketose, dry (−1630.0, FF s5); ketose→aldose (−766.5, FF s6)
2. **Non-anomeric** β-elimination dehydration in which the leaving –OH is protonated by, or relayed
   via, a **vicinal** –OH (or there is a clear β-H), forming C=C + H₂O:
   - open-glucose→3-deoxy-enol (−1410.1, HMF s1); 3-DG→3,4-DGE (−1533.0, HMF s3)
   - xylose→xylo 3-deoxy-enol (−1459.8, FF s7); →xylo unsaturated dicarbonyl (−1541.1, FF s9)
3. Ring open/close (hemiacetal/hemiketal), **only if** the anomeric carbon carries a **vicinal** –OH
   that can relay the proton intramolecularly:
   - retro-hemiketal ring closure to the furanic hemiketal (−1574.5, HMF s4)
   - hemiketal ring closure on the C5 backbone (−1621.5, FF s10)
4. **Aromatizing** anomeric dehydration: loss of the anomeric –OH with formation of an aromatic furan.
   The aromatization free energy is what keeps the step concerted and neutral. e.g. the hemiketal
   O=CC1(O)C=CC(CO)O1 → HMF (−830.4, HMF s5); furanic hemiketal → furfural (−872.9, FF s11).
   This is the only anomeric C–O event that can be strict.
5. Retro-aldol C–C cleavage **activated by a β-carbonyl**, with the β-OH proton relayed through a
   six-membered cyclic transition state. Requires a carbonyl β to the breaking C–C; a plain aldose does
   **not** qualify (see F).
   - open-fructose → glyceraldehyde + DHA-enol (−758.1, HAA s2)
   - glyceraldehyde → glycolaldehyde-enol + HCHO (−942.1, HAA s3)
   - 3-ketohexose → C5 enediol + HCHO (−932.3, FF s4) — the C6→C5 bridge

> One accepted step does not follow the no-catalytic-water rule: HAA s4, a water-catalyzed enol→keto
> tautomerization (−920.1). It stands as delivered but is not a template for new candidates — do the
> equivalent dry (motif 1) instead.

## Not STRICT-ABLE (these pass through a charged intermediate, so a raw IRC endpoint is charged)
A. Non-aromatizing anomeric dehydration (forms an enol ether / oxocarbenium): barrierless E1 to the
   oxocarbenium. e.g. fructofuranose→enol ether, and the subsequent enol-ether dehydration. Raw IRC
   endpoint = cation.
B. Hemiketal closure / ring opening at an anomeric carbon that **lacks** a vicinal –OH relay partner (e.g. the
   anomeric C flanked by a carbonyl/CHO and a ring C=C, as in deoxy/dehydrated intermediates): the C–O
   forms first, giving a **zwitterion** (oxocarbenium + alkoxide). DFT gives a 2nd/high-order saddle (two large imag
   modes = C–O formation + proton transfer are separate). e.g. enedione→hemiketal, 3-DG→furanose.
C. Exocyclic-CHO formation on/adjacent to the anomeric carbon (enolization across the anomeric C):
   goes through a zwitterion. Charged.
D. Allylic/vinylogous 1,3-OH transposition: non-elementary (2nd-order saddle, slides to ionization).
E. Vinylogous (>4 Å) proton-shift dehydrations: not a single elementary neutral step.
F. Retro-aldol on an **aldose** (no carbonyl β to the breaking C–C), e.g. open-glucose C2-C3: a saddle can
   be located, but the IRC recombines to the reactant instead of separating the fragments (shown by four
   independent attempts). Isomerize to the ketose / 3-ketose first, then cleave (motif 5).

## Key discriminator (use when ranking candidate edges)
- **Anomeric carbon** = the ring carbon bearing both the ring O and an exocyclic O (OH/OR).
- An anomeric C–O make/break is STRICT-ABLE only if (i) it is aromatizing, or (ii) it is a ring
  open/close with a vicinal –OH relay partner on the anomeric carbon.
- A dehydration is STRICT-ABLE only if it is non-anomeric and has a vicinal –OH / β-H.
- Tautomerizations (no C–O make/break, no charge) are generally STRICT-ABLE.

## Why the CHO must arrive during aromatization (the constraint that shaped the HMF route)
This is the structural argument that leaves only two ways to reach HMF, and it is what the accepted
chain follows: `glucose_hmf_review_v3` delivers the CHO by the concerted **aromatizing** dehydration
(motif 4, −830.4, s5) after a vicinal-OH relayed ring closure (−1574.5, s4). Use the argument to rank
candidate anomeric edges.

HMF has an exocyclic CHO on the anomeric ring carbon. Creating that CHO, OR closing the deoxy ring to
bear it, is an anomeric event **without** a vicinal –OH relay **and** non-aromatizing → charged (type B/C).
The two ways to keep a vicinal-OH relay at the anomeric C are mutually exclusive on a redox-neutral path
(native-CHO open backbone closes at the deoxy stage; fructose-closed route must create the CHO later).
Consequently, a fully-strict route must contain a sequence in which the CHO is either (a) created by a
non-anomeric, vicinal-OH-relayed dehydration on a carbon *not* adjacent to the anomeric center, or (b)
created concertedly *during* an aromatization (motif 4). Any other route to the CHO is non-strict.

## How to use
When given a candidate edge reactant>>product (+coproduct): identify the anomeric carbon(s), classify
the bond change, map it to the lists above, and report STRICT-ABLE or not, citing the matching rule id. Only
spend QM (tools/workflow/validate_candidate.py) on STRICT-ABLE edges. For route search, keep only STRICT-ABLE
edges in the graph and look for a glucose→HMF path; report the path or the blocking edge-class.
