# Operations

## Install and projects

Use Python 3.12 and `pip install -e ".[dev]"` in a fresh virtual environment.
`scripts/bootstrap.sh` is a convenience wrapper. The same package can be built
as a wheel; schemas, templates and skills are bundled, so installation does not
require a source checkout or another private project environment.

`mvt project init ./my-project --template fixture-stage` creates an independent
project. Inputs and outputs stay under that project. `mvt build --no-step` permits
a geometry preview before STEP delivery. Build, render and audit share a contract
and semantic model hash. STEP bytes may change with exporter metadata.

## Exit codes

- 0: completed with no RED status
- 2: invocation or unclassified runtime failure
- 3: invalid contract or source lock
- 4: CAD/STEP/render failure
- 5: audit RED
- 6: governance operation blocked

`--json` returns structured results and failures. Physical and safety YELLOW
limits are separate from a geometry PASS. Preserve both in reports.

## Optional workspace governance

CAD and MCP do not need the local index, rule promotion or prompt system.
To initialize governance in a new empty workspace:

```bash
mvt workspace init ./workspace
cd ./workspace
mvt index rebuild
mvt tool validate
```

Governance commands use the current directory or explicit `MVT_WORKSPACE`.
Skill install/sync reads bundled resources; use `--target` to choose a temporary
or host-specific skills directory. Only the two MVT skill names are managed.
No skill is installed globally without an explicit user command.

Acceptance is explicit: `mvt accept <project> <artifact>`. Rejected hashes cannot
be silently accepted; changed accepted content is RED. Keep accepted copies and
ledgers with their project when archiving it. Public example media is synthetic
release evidence, not a customer acceptance ledger.

Rule promotion defaults to disabled through `governance/AUTO_PROMOTION_DISABLED`.
Candidate evaluation is advisory, evidence-backed and workspace-local. Enable
only deliberately. Versions and rollback records remain local. Generate a
workspace prompt only after its tests and evidence have passed; do not commit
private prompts or internal runtime state.

The public release starts with a fresh Git history. Never add a private source
repository, local `.env`, old runtime index, private CAD or raw conversations to
it. Run the release checks before committing new example artifacts.
