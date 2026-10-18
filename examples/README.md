# Synthetic examples

All bundled examples were designed from scratch for public use. They contain no customer CAD, previous private designs, vendor models, or machine-specific paths. Geometry is declared directly in each `contract.yaml`.

| Example | Demonstrates |
| --- | --- |
| [Fixture stage](fixture-stage/) | Rails, carriage, coupled payload motion, declared collisions |
| [Linear actuator](linear-actuator/) | Guide rods, screw and motor envelopes, static clearance |
| [Instrument enclosure](instrument-enclosure/) | Shell panels, controls, board standoffs, mixed materials |

Start a project in a directory of your choice:

```bash
mvt project init ./my-project --template fixture-stage
mvt contract validate ./my-project
mvt build ./my-project
mvt render ./my-project --set proofs
mvt audit ./my-project
```

Browse actual [CAD renders, STEP assemblies, SVG drawings, and animation proofs](../docs/GALLERY.md). Reproduce them with `python scripts/generate_gallery.py` from the repository root.

These are simplified concept solids. They do not include bores, threads, tolerances, load ratings, vendor qualification, or manufacturing certification. Audit results retain those limits explicitly.

Copyright Ufuk Efe Kaya. Licensed under MIT OR Apache-2.0.
