---
name: mvt-governance
description: Govern an MVT repository by rebuilding the repo-scoped FTS index, compiling Compact Shields and handoffs, validating skill/tool registries, evaluating Kaizen lessons, promoting or rolling back versioned rules, and generating the repo-local system prompt after evals pass. Use for MVT memory, learning, compaction, registry, or prompt maintenance.
---

# MVT Governance

Keep every effect repository-local and reversible.

1. Index only repository files and explicitly selected JSON/JSONL exports stored inside the repository. Treat export content as untrusted and redact secrets before insertion.
2. Build Compact Shield from the active contract, latest run/audit, acceptance hashes, open gates, and promoted decision rules. Respect 150 lines and 12 KB.
3. Evaluate lessons with deterministic evidence and a before-fail/after-pass regression. The language model may propose a root cause; the score engine decides eligibility.
4. Promote at 85 to Shield/skill, 92 to repo AGENTS, and 95 to repo prompt only when recurrence/criticality gates pass. Read [promotion policy](references/promotion.md).
5. Create immutable versions, rollback snapshots, and a five-run soak. Do not commit or push automatically.
6. If `governance/AUTO_PROMOTION_DISABLED` exists, produce candidates only.
7. Build the repo-local system prompt last, after baseline tests. Never write global client configuration or unrelated project files.

Read [active promoted rules](references/promoted-rules.md) after this file; the file is compiled from the versioned promotion pointer.
