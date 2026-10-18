# MCP tools

Run `mvt-mcp --workspace <existing-directory>`. The server speaks stdio using
the official Python MCP SDK. Keep its standard output connected to the client;
diagnostics belong on standard error.

| Tool | Behavior |
| --- | --- |
| `mvt_templates` | List synthetic templates and resource limits |
| `mvt_project_create` | Copy a template into a new, empty project |
| `mvt_contract_read` | Return validated contract data and its hash |
| `mvt_contract_write` | Save validated declarative geometry; compare hash on updates |
| `mvt_contract_validate` | Validate schema, references and source locks |
| `mvt_model_build` | Build B-rep solids; export and reload STEP unless deferred |
| `mvt_render_proofs` | Render one declared camera or all proof cameras |
| `mvt_model_audit` | Audit the current geometry and accepted-artifact hashes |
| `mvt_animation_build` | Render and audit a bounded deterministic sequence |
| `mvt_step_inspect` | Load actual STEP topology, volume and bounds |
| `mvt_step_drawing` | Write a new native SVG projection drawing |
| `mvt_artifacts` | List current run artifacts and hashes |
| `mvt_artifact_preview` | Return a hash-verified PNG/JPEG proof as an MCP image |

All paths are workspace-relative. Parent traversal, absolute paths and symlink
escapes are rejected by the tool boundary. Hash-locked CAD source files must
also live under the owning contract directory. The server does not discover
other projects, read account credentials, run arbitrary code or send network
requests to a modeling service.

Limits: 1 MiB contract data, 1,000 entities, 16,777,216 pixels per render,
300 animation frames, 128 MiB per inspected/drawn STEP file. Previews are limited
to 8 MiB and the same render pixel budget. The default CAD worker timeout is 180 seconds; an operator
can select 1–1,800 seconds with `--timeout`. Workers run serially in isolated
Python processes and are terminated as a process group on a POSIX timeout.

This is a local filesystem boundary, not a container or an operating-system
sandbox. Run under an OS user with access only to the work it needs. STEP/BREP
parsing and rendering use native libraries; untrusted files still need the
usual isolation at the host level.

MCP results report local evidence. Artifact creation does not mean a person has
accepted it. Human acceptance remains an explicit CLI workflow. Physical and
safety qualification remain distinct from a geometry audit.
