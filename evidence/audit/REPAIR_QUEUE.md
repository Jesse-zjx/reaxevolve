# REPAIR_QUEUE (post STRICT v5 readjudication)

Items: **7**

| edge | action | reason |
|---|---|---|
| `O=C(C(O)CO)C(O)C(O)CO>>O=C(C=C(O)CO)C(O)CO` | verify_geometry | provisional keep from record; locate final .out/.xyz |
| `O=C(C=C(O)CO)C(O)CO>>O=C(CO)CC(=O)C(O)CO` | verify_geometry | provisional keep from record; locate final .out/.xyz |
| `O=C(CO)C(O)C(O)C(O)CO>>O=C(CO)C(O)=CC(O)CO` | verify_geometry | provisional keep from record; locate final .out/.xyz |
| `O=C(CO)C(O)C(O)C(O)CO>>OC=C(O)C(O)C(O)C(O)CO` | verify_geometry | provisional keep from record; locate final .out/.xyz |
| `O=C(CO)C(O)C(O)CO>>O=C(C=C(O)CO)CO` | verify_geometry | provisional keep from record; locate final .out/.xyz |
| `O=CC(O)C(O)=CC(O)CO>>O=CC(O)C(=O)CC(O)CO` | verify_geometry | provisional keep from record; locate final .out/.xyz |
| `OC1CO1>>O=CCO` | verify_geometry | provisional keep from record; locate final .out/.xyz |

## Policy
- Try soft-mode cleanup / re-guess OptTS+NumFreq+IRC before demotion.
- If irreparable: demote from STRICT pin + network projection to `evidence_ok` or `rejected`; keep attempt provenance.
- Do not overwrite attempt records without a provenance note.

Generated: 2026-08-08 23:38:15
