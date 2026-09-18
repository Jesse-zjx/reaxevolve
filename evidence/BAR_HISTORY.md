# The acceptance bar changed during the campaign, and one deposited step predates the change

The three deposits were not all accepted against the same criterion. Any figure or sentence
asserting a single fixed standard throughout the campaign is wrong. This note records what
changed, when, and which deposited step is affected.

## The versions, in order

**Version 1 — connectivity-layer match.** A step passed if the IRC endpoints matched the
intended species at the InChI carbon-skeleton layer, with keto/enol or zwitterion tautomerism
annotated rather than disallowed. The previous revision of `references.md` was written to defend
this version, citing the literature practice of the same relaxation.

**Version 2 — exact neutral SMILES.** A transcript message dated 2026-05-31 reads
`最好是精确匹配SMILES 吧`, the human proposing that both endpoints match the neutral species
exactly. This became `EXACT_SMILES_ONLY` and is the core of the bar as it now stands.

**Version 3 — water shuttles permitted.** A later message announces a
`New acceptance criterion (literature-grade, user-approved)` under which a step is acceptable if
its single transition state has IRC ends corresponding to the neutral reactant and product, with
*explicit water molecules allowed as neutral proton-shuttle catalysts*.

**Version 4 — zero spectator water, current.** After the furfural review the expert rejected any
**new** step whose raw IRC carries a standalone H2O on both endpoints, on the grounds that such a
water has no provenance in the chain and breaks atom-count chaining. `water_relay_guess.py`
carries this in its own header and is marked deprecated for new edges because of it.

## Which deposited steps are affected

Nineteen of the twenty deposited steps meet the current bar. One does not.

| Deposit | Steps | Spectator water | Status against the current bar |
|---|---|---|---|
| `glucose_hmf_review_v3` | 5 | none; no spectator field in the manifest | meets it |
| `glucose_ff_review_v1` | 11 | `spectator_water` field present, empty on every step | meets it |
| `glucose_haa_review_v1` | 4 | step 4 carries `spectator=H2O (catalytic relay)` | **accepted under version 3** |

HAA step 4 is a genuinely water-mediated tautomerization at −920.1 cm⁻¹. It was produced by the
water-relay generator and accepted as delivered before version 4 took effect. It was not
grandfathered by oversight — the tightening was explicitly scoped to new work — but a reader who
applies the current bar to the deposits will find this step failing it.

## What the paper has to say

State the bar as it finally stood, and disclose that HAA step 4 was accepted under the preceding
version which permitted a neutral water shuttle. Nineteen of twenty steps under the strictest
version is a stronger and more credible claim than twenty of twenty under an unstated mixture.

The water-relay control now running includes HAA step 4 as its positive control: allowing the
relay should recover the deposited saddle. If it does, the disclosure comes with evidence that
the step is sound on its own terms rather than merely exempted.
