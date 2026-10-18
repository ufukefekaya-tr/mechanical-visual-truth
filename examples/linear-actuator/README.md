# Compact screw actuator

A synthetic actuator with a dark bed, teal end supports, two guide rods, a gold screw envelope, and a contrasting carriage. The motor is a generic envelope; the screw is a plain cylinder. No vendor model is imported.

All units are millimetres. These simple solid envelopes illustrate concept verification; bores, threads, tolerances, forces, and vendor specifications are not represented. They are not manufacturing drawings.

```bash
mvt contract validate examples/linear-actuator
mvt build examples/linear-actuator
mvt render examples/linear-actuator --set proofs
mvt audit examples/linear-actuator
```

Source: original synthetic public example, created without importing prior customer or personal geometry and dimensions.

Copyright Ufuk Efe Kaya. Licensed under MIT OR Apache-2.0.
