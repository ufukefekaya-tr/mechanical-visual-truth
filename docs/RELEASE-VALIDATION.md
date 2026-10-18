# Release validation — 0.2.0

Validated on 18 October 2026 with CPython 3.12 on Linux.

- 78 tests passed, with zero failures, errors or skips.
- Actual stdio client initialization and tool discovery passed for all 13 tools.
- MCP project creation, contract validation, B-rep/STEP build, proof rendering,
  geometry audit, STEP inspection, native SVG drawing and native image preview
  passed through a real client/server session.
- Wheel and source distribution built successfully. A separate virtual
  environment loaded the installed wheel outside the source checkout and
  initialized/validated an example using bundled resources; doctor passed.
- Three gallery examples were built, rendered, audited, independently reloaded
  from STEP and compared to their source geometry. Geometry checks passed;
  physical/safety limits are still YELLOW and recorded in each audit.
- Gallery views, orthographic drawing rasters and animation contact sheet were
  visually inspected. Artifact hashes are in assets/gallery-manifest.json.
- The selected public tree was checked for private project identifiers,
  workstation paths and known credential formats. No matches were found.

This records the checks performed, not a certification of mechanical safety,
manufacturability, malicious-CAD robustness, or all possible CAD inputs.
The CI workflow repeats tests and installed-wheel validation for new changes.
