# Workflow

## New project

Use `mvt project init <slug>`, then define a stable coordinate system, envelope, entities, requirements, cameras, and optional motion sequences. Vendor substitutes must be measured envelope proxies marked `commercially_unverified`.

## Evidence chain

The run manifest binds contract hash, semantic model hash, STEP, proof render, audit, camera, and animation artifacts. Exact-top cameras use parallel projection. A proof image with negligible pixel variance is invalid.

## Presentation

Accept only an audited deterministic render as the reference source. `mvt present prepare` lists immutable geometry and allowed cosmetic changes. After image generation, compare silhouette, counts, station placement, forbidden geometry, and clearances to the reference.

## Acceptance

`mvt accept` copies a content-addressed artifact under `accepted/`; it never overwrites. `mvt reject` records a hash and reason. A rejected hash cannot become a presentation target.
