# Two-rail fixture stage

A small fixture stage: a blue base, two guide rails, a carriage, and a brass demonstration payload. The carriage, bearing carriers, fasteners, and payload move as one declared group.

Animate with `mvt animate build examples/fixture-stage --sequence shuttle`.

All units are millimetres. These simple solid envelopes illustrate concept verification; bores, threads, tolerances, forces, and vendor specifications are not represented. They are not manufacturing drawings.

```bash
mvt contract validate examples/fixture-stage
mvt build examples/fixture-stage
mvt render examples/fixture-stage --set proofs
mvt audit examples/fixture-stage
```

Source: original synthetic public example, created without importing prior customer or personal geometry and dimensions.

Copyright Ufuk Efe Kaya. Licensed under MIT OR Apache-2.0.
