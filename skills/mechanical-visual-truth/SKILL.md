---
name: mechanical-visual-truth
description: Build and verify contract-driven mechanical concepts with deterministic CadQuery solids, STEP, VTK proof renders, motion animation, imagegen presentation packaging, audits, acceptance records, and handoffs. Use for mechanical concept creation, geometry correction, proof camera renders, clearance/collision checks, or technical animation in an MVT project.
---

# Mechanical Visual Truth

Read the active project `contract.yaml`, latest run manifest, acceptance ledger, and `COMPACT_SHIELD.md` before changing geometry.

1. Validate with `mvt contract validate <project>`.
2. Change dimensions, counts, topology, stations, cameras, and motion only in the contract. Do not duplicate contract numbers in modeling code.
3. Run build, proof render, and audit. A RED gate blocks presentation and acceptance.
4. For motion, use deterministic CAD sequences for technical claims. Read [motion workflow](references/motion.md). Use presentation-only 2.5D packages only to explain operation.
5. Run `mvt present prepare` before image generation. Image generation may change material, light, and studio appearance only.
6. Audit the returned presentation against the locked package, then ask the user to accept or reject it.
7. Generate a handoff/Shield when work spans agents or compaction.

Never promote imagegen output or raster animation to the technical master. Never use a rejected reference. Never install or modify skills outside the MVT namespace.

Read [workflow](references/workflow.md) for command order and evidence handling.
