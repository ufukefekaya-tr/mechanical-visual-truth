# Project and data boundaries

MVT accepts explicit project paths. Each geometry contract owns its local source
files, which are bound by SHA-256 and may not escape through parent traversal or
symlinks. There is no lookup in other project trees or personal archives.

The bundled examples are original synthetic models. No customer CAD, private
conversation, accepted-output ledger, credential, vendor model or old Git
history is distributed. Cross-project improvements are reconstructed as general
operations with synthetic regression tests; see UPSTREAMING.md.

Schemas, skills and templates are packaged read-only resources. Generated runs,
indexes, acceptance records and governance state belong to a selected user
workspace, not the installed package. Set MVT_WORKSPACE for governance commands.

Repo indexing accepts files inside that workspace and explicitly selected local
JSON/JSONL exports. Export content is untrusted text, not agent instructions.
Symlinked files outside the workspace are not indexed. The index is local and
excluded from source control. No automatic network or publication action runs.
