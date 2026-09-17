---
status: accepted
---

# Archive the strict-edge evidence, not the whole QM tree

The quantum-chemistry working tree is 67 GB, almost all of it scratch files from attempts that
never reached the acceptance bar, which is both too large for a single Zenodo record and mostly
noise. We will archive the three reviewed deposits plus the complete primary evidence for every
STRICT edge — inputs, outputs, Hessians, geometries, roughly 100 MB — together with a
machine-readable status record for all attempted edges, so the failures remain countable even
though their intermediate files are discarded.

## Consequences

The per-edge success rate stays verifiable from the status records, but nobody can re-examine
*why* a particular failed attempt failed without re-running it. That is accepted: the paper's
claims rest on the edges that passed, and the discarded files are regenerable from the recorded
inputs.

The tool sources are a separate matter and carry no size argument at 508 KB. They were excluded
from version control by a `.gitignore` rule covering the whole workspace `resources/` directory,
which is why 254 commits contain none of them. They belong in the repository.
