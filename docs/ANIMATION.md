# Animation output and trust

MVT produces animation at the end of a verified mechanical run.

## Deterministic CAD motion

The contract names actors, keyframes, coupled groups, collision pairs, camera, frame rate, duration, and sample density. Each frame transforms the same CadQuery B-rep entity list used by STEP and proof PNG. The output directory contains:

- H.264/yuv420p MP4
- reduced looping GIF
- six-frame contact sheet
- motion audit and animation manifest

The manifest binds contract/model hashes and declares `truth_mode: deterministic_cad`. It is evidence only for the sampled states and declared constraints; it is not a dynamic physics or FEA solver.

## Presentation-only 2.5D

This mode captures a useful workflow learned from an anonymized prior animation task: fixed accepted backgrounds, alpha-isolated actor sprites, background cleanup, smoothstep timing, coupled transforms, visible axis/rotation cues, then MP4/GIF/contact-sheet encoding. It is effective for explaining process order when full kinematics are unavailable.

Its package must declare `truth_mode: presentation_only_2_5d` and burn in a concept disclaimer. It can never satisfy collision, clearance, CAD, physics, or manufacturing gates. The regression to remember is simple: moving a carriage without its payload is mechanically false even when the animation looks plausible.
