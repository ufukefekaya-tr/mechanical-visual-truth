# Cross-project improvements and provenance

The public release generalizes reusable work found in later private STEP-producing
projects. Original private projects were reviewed read-only. The public examples
are new synthetic models; their contracts, STEP files, drawings and renders are
generated entirely inside this repository.

## Changes brought into the public implementation

| Evidence from reviewed revisions | Public behavior |
| --- | --- |
| Sheet prototype V1 and enclosure R7/R8 independently reload exported STEP | `mvt.step_io.inspect_step` reads actual native CAD, reports solid count, validity, world bounds, volume and SHA-256. |
| Independent reconstructed geometry checks in R7/R8 | `compare_shapes` checks individual reloaded solids and uses actual boolean symmetric-difference volume by default. Equal outer bounds and volume cannot hide a relocated internal feature. |
| Immutable assembly reuse and named STEP recovery | `match_step_solids` binds explicit registry IDs to unique solid signatures, verifies an optional source hash, and rejects ambiguous or reused matches. It never infers stable IDs from STEP import order. |
| Native recovery/assembly bounds disregard cached render meshes | Native signatures use OpenCascade `AddOptimal` with triangulation disabled. Rendering a part does not change its geometry signature. |
| R8 drawings and corner checks use real B-rep sections, including inclined planes | `mvt.drawings.section_edges` and `section_plane_edges` intersect any model with an explicit datum or arbitrary plane; empty intersections remain empty. |
| R8 derives drawing profiles from the CAD source | `export_step_drawing` reloads any valid solid STEP and creates top/front/right SVG views using native hidden-line removal, with one common scale and true overall dimensions. |
| Accepted artifacts are immutable and identity is hash-bound | New drawing/round-trip APIs refuse to overwrite by default. Export verification completes in a temporary file before an atomic, no-clobber write. |

The STEP helpers and drawing functions accept caller-provided paths and geometry.
They do not depend on private names, dimensions, contracts, directories, source
ledgers, project-specific adapters or external services. SVG text is XML-escaped.

`verify_step_roundtrip` offers a standalone export/reload path. The regular MVT
build also reloads and verifies its named/color STEP assembly; it retains the
assembly exporter instead of replacing the file with an unnamed compound.

The stricter geometry comparison catches changes in internal geometry, whereas
`match_step_solids` proves correspondence by declared bounds/volume only. A
correspondence record does not prove identical internal features. Callers that
need that guarantee must use source hashes and/or native geometry comparison.

## Reviewed source fingerprints

These are sanitized revision labels and SHA-256 fingerprints of the reviewed
source files, not copies of those projects. Full original filesystem paths,
customer names and vendor identifiers are intentionally absent. Labels describe
the workstream and revision date; they do not claim public upstream availability.

| Reviewed revision | Source filename | SHA-256 |
| --- | --- | --- |
| CAD utilities / 2026-08-22 | `cad_utils.py` | `8df05c15d1744b6d20eed74e563eb05a6de553060590cb16b671b8b44ebf9612` |
| Sheet prototype V1 / 2026-10-09 | `generate.py` | `d2eb0e31aa46d47f0666ad9dfc45e9c029c46420c380dddde1508127023af471` |
| Sheet prototype V1 / 2026-10-09 | `verify.py` | `b321e490e80ccb0272cc87847b204e9d4e93a584971b9f4a750bcf971f5e7d20` |
| Sheet enclosure R7 / 2026-10-09 | `verify.py` | `ff19b449507fa03e46c5eb9de8336d81e0ca06d359997e40f12f6ca3a53cc3d4` |
| Sheet enclosure R8 / 2026-10-13 | `build.py` | `35011894a6d3194dda50df56899637f00f365e2fb998401fb183c04d02e29291` |
| Sheet enclosure R8 / 2026-10-13 | `verify.py` | `7b9fb8ed387e7f35804b772d38d3573746f6dcedeec9e6019d9ca45fe4a4f568` |
| Sheet enclosure R8 / 2026-10-13 | `drawing.py` | `dac85990a92d926e5164327cfd616ea4c5760c6a970ddd594716ba4a4cf336f7` |
| Sheet enclosure R8 / 2026-10-13 | `corner_sections.py` | `a40d945cf32f625f9c04773ed4270b413d791905345d21aff843a1bfbb90d5c5` |
| Sheet drawing Rev B / 2026-10-09 | `create_drawings_rev_b.py` | `6f4dac5b798ce93a42d4b4ede2e1b931ad17f3834493d86ff33482a8ef0d2aa9` |
| Assembly reuse / 2026-09-26 | `assembly_adapter.py` | `889f418ae4b7297ccfc921e09b7bf4ec7c54d66d339534214be455728092a66a` |
| Named STEP recovery / 2026-09-26 | `step_recovery.py` | `3ef73f9438f50ec93983b0c1482d91c10751c6332b5599de9021e4ecb51227fd` |
| Native assembly / 2026-09-27 | `native_source.py` | `9756e3bd7cae43430ceb1f3a929f728870df12955751de3f7a48043988df5fe8` |
| Prototype mesh cache / 2026-09-26 | `native_runtime.py` | `ee44edcbfd2b60f0926d93562114a4cbe788d432d743449cfb8bc2ddfb7e2943` |
| Project fork / 2026-09-28 | `source_lock.py` | `2036a391d517b738a84550c339a57e07a39d45bff07b546f4d5accaf703f6974` |
| Project fork / 2026-09-28 | `support_audit.py` | `ef93bbb0d56147dcbbb011c3b6e71a06714f5092b20138eca75b97900991a64e` |
| Project fork / 2026-09-28 | `capture_linkage_audit.py` | `615d9c67df064594b345af51352f82e7b3e71b46b94a08c193d3506dd3c267f9` |
| Project fork / 2026-09-28 | `vtk_renderer.py` | `30f49c4ed28712b81a3d072d0ffe7095568230a135943455da019709ac1513ad` |
| Project fork / 2026-09-30 | `blender_bridge.py` | `cdffd3aa27879df87484fd71a48af6e4c582ac10b0f67c3f38c47c18d8be5b0f` |

## Deliberately excluded from extraction

- Customer CAD, renders, drawings, original STEP/BREP/DXF, contracts, accepted
  artifact ledgers, private output archives and source data.
- Vendor part dimensions, enclosure features, material/process assumptions,
  bend/relief development, cable and clamp reservations, mounting patterns and
  product-specific manufacturing notes.
- Assembly counts, hardcoded source hashes and locations, runtime monkey patches,
  bespoke recovery sidecars, cache authority chains and machine kinematic routes.
- Whole-sale copying of later project frameworks. Motion support/contact proofs,
  linkage-specific logic, mesh-instance recovery and the optional Blender bridge
  are reviewed separately; a fingerprint in this inventory does not imply that
  every behavior from that file is supported by this release.

The SVG dimensions are overall CAD envelopes. They do not replace feature-level
dimensions, fits, tolerances, certified vendor geometry, structural calculations
or first-article manufacturing checks. The release makes no automatic unfolding
or universal mechanical validation claim.

## Regression evidence

Synthetic tests verify separate-solid STEP reload, displaced/missing solids,
an internal hole moved without changing total volume or outer bounds, malformed
and empty STEP files, unique registry matching, immutable output preservation,
triangulation-independent native bounds, XML-safe technical views and actual
world-coordinate CAD sections. No production customer model is needed to run them.
