---
status: accepted
---

# Date accepted edges from the verdict record, not from the transcripts

The reaction-network edge records carry no date field, so the graph alone cannot say when any step
was accepted, and the file modification times are useless because the migration out of the old
harness rewrote almost all of them on one day. The dates that a cumulative capability curve needs
turn out to be one level down, in the per-run verdict files, each of which was written with a
`time` field at the moment the judgement was made. We date every accepted edge from there, taking
a record whose status is STRICT, and we date the three deposits independently from the
`Starting time` header that ORCA writes into its own output. Both are machine-written, both are
complete — 35 of 35 edges and 40 of 40 deposit outputs — and neither requires interpretation.

## Considered options

Before the `time` field was noticed, the dates were reconstructed by matching each transition
state's imaginary frequency against the agent transcripts, on the reasoning that the frequency is
a unique fingerprint. It is unique — no two accepted edges share a value to one decimal place —
but the approach fails anyway, and it fails in a way that looks like success:

- Matching the frequency rounded to an integer covers 34 of 35 edges, which is why it was
  tempting. It also collides (`1533` matches two different edges) and it disagrees with tighter
  matching on 21 of the 35, always by dating the edge *earlier* — in one case by 45 days — because
  a bare three- or four-digit number matches unrelated quantities in the surrounding text.
- Restricting matches to the signed or decimal forms removes the false positives and drops
  coverage to 26 of 35.
- Additionally requiring a frequency marker such as `cm-1` or `imag` within 90 characters drops
  coverage further, to between 19 and 25 of 35, because much of the output that reports a
  frequency does so in terse tables with no marker nearby.
- Under every tight variant, several of the surviving dates land in the 2026-08-01 audit session,
  where earlier results were being discussed retrospectively. Those are not discovery events.

There is no setting that is both complete and clean, so the method was abandoned rather than
tuned. Recording this is the point of the ADR: the fingerprint idea is attractive enough that the
next person to need these dates will try it, and the failure mode is quiet.

## Consequences

Transcripts are still read, for one thing only: the asset-evolution events, which have no
machine-written record anywhere. Those dates are therefore weaker than the edge dates and are
reported as such — each carries the number of turns between the sighting and the nearest
timestamped message, since agent turns are not themselves timestamped. Each is also reported
alongside the number of edges accepted before it, which bounds what the asset can be credited
with regardless of how the narrative reads. On that measure the dry proton-transfer tool arrives
late enough that only 2 of the 35 accepted edges follow it.

The surviving quantum-chemistry scratch tree begins at 2026-07-25, so it cannot corroborate any
asset date earlier than that. Nothing in the package can. Asset dates before that point rest on
the transcripts alone.
