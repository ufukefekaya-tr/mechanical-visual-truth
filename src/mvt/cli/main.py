from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from mvt import __version__
from mvt.acceptance import accept, reject, verify_accepted
from mvt.auditing import audit_contract_model
from mvt.contracts import load_contract
from mvt.errors import MVTError
from mvt.geometry.model import build_model, export_step, model_semantic_hash
from mvt.governance.prompt import build_prompt, rollback_prompt, verify_prompt
from mvt.governance.shield import build_shield
from mvt.indexing import query_index, rebuild_index
from mvt.kaizen.engine import evaluate_lesson, promote_lessons, rollback_promotion
from mvt.manifest import create_run, latest_run
from mvt.presentation import prepare as prepare_presentation
from mvt.registry.skills import skill_action
from mvt.registry.tools import set_enabled, validate_registry
from mvt.rendering.animation import audit_motion, build_cad_animation, prepare_2_5d_package
from mvt.rendering.vtk_renderer import render_png
from mvt.util import atomic_json, read_json, repo_root, resource_root, sha256_file, utc_now
from mvt.operations import initialize_project, build_project, current_build, render_project, audit_project, templates


def _result(data: Any, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(data, dict):
        status = data.get("status", "OK")
        details = data.get("path") or data.get("run_id") or data.get("project") or ""
        print(f"{status}{': ' + str(details) if details else ''}")
        for key in ("contract_hash", "model_hash", "database", "promotion_id"):
            if data.get(key):
                print(f"{key}: {data[key]}")
        for artifact in data.get("artifacts", []):
            print(f"artifact: {artifact.get('path')} sha256={artifact.get('sha256')}")
        if data.get("findings"):
            for finding in data["findings"]:
                if finding.get("status") != "PASS":
                    print(f"{finding.get('status')}: {finding}")
    elif isinstance(data, list):
        for item in data:
            print(json.dumps(item, ensure_ascii=False))
    else:
        print(data)


def _doctor(_: argparse.Namespace) -> dict[str, Any]:
    checks = []
    for module, expected in (("mcp", None), ("cadquery", "2"), ("vtk", "9"), ("PIL", None), ("numpy", None), ("yaml", None), ("imageio_ffmpeg", None)):
        try:
            loaded = importlib.import_module(module)
            checks.append({"name": module, "status": "PASS", "version": getattr(loaded, "__version__", "available")})
        except Exception as exc:
            checks.append({"name": module, "status": "RED", "error": str(exc)})
    git = shutil.which("git")
    checks.append({"name": "git", "status": "PASS" if git else "RED", "path": git})
    try:
        import sqlite3

        fts = bool(sqlite3.connect(":memory:").execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0])
    except Exception:
        fts = False
    checks.append({"name": "sqlite_fts5", "status": "PASS" if fts else "RED"})
    if any(item["status"] == "RED" for item in checks):
        status = "RED"
    else:
        status = "PASS"
    return {"status": status, "mvt": __version__, "python": platform.python_version(), "workspace": str(repo_root()), "resources": str(resource_root()), "checks": checks}


def _contract_validate(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.project)
    return {"status": "PASS", "project": contract.project_id, "contract_hash": contract.hash, "entities": len(contract.entities)}


def _project_init(args: argparse.Namespace) -> dict[str, Any]:
    return initialize_project(args.slug, args.template)


def _build(args: argparse.Namespace) -> dict[str, Any]:
    return build_project(args.project, write_step=not args.no_step)


def _require_run(project: str):
    return current_build(project)


def _render(args: argparse.Namespace) -> dict[str, Any]:
    if args.set != "proofs" and not args.camera:
        raise ValueError("Select --set proofs or --camera <id>")
    return render_project(args.project, camera_id=args.camera)


def _audit(args: argparse.Namespace) -> dict[str, Any]:
    return audit_project(args.project)


def _step_inspect(args: argparse.Namespace) -> dict[str, Any]:
    from mvt.step_io import inspect_step
    return inspect_step(Path(args.path))


def _step_drawing(args: argparse.Namespace) -> dict[str, Any]:
    from mvt.drawings import export_step_drawing
    return export_step_drawing(Path(args.path), Path(args.output), title=args.title)


def _workspace_init(args: argparse.Namespace) -> dict[str, Any]:
    target = Path(args.path).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError("Workspace initialization requires an empty directory")
    target.mkdir(parents=True, exist_ok=True)
    for name in ("schemas", "skills", "tools", "governance/templates", "governance/prompts/templates", "governance/rules"):
        source = resource_root() / name
        if source.exists():
            shutil.copytree(source, target / name, dirs_exist_ok=False)
    (target / "governance" / "AUTO_PROMOTION_DISABLED").write_text("Explicit review required.\n")
    return {"status": "PASS", "workspace": str(target)}


def _animate_build(args: argparse.Namespace) -> dict[str, Any]:
    contract, run, solids = _require_run(args.project)
    sequence = contract.animation(args.sequence)
    output = run.output("animations", args.sequence)
    if sequence["truth_mode"] == "deterministic_cad":
        manifest = build_cad_animation(contract, solids, run.data["model_hash"], args.sequence, output)
        path = output / "animation-manifest.json"
        run.add_artifact(path, "animation-manifest", sequence=args.sequence, truth_mode=sequence["truth_mode"])
        if manifest["motion_audit"]["status"] == "RED":
            run.data["status"] = "RED"
            run.save()
        return manifest | {"status": manifest["motion_audit"]["status"]}
    package = prepare_2_5d_package(contract, args.sequence, output)
    return package | {"status": "YELLOW", "reason": "presentation package prepared; no technical motion claim"}


def _animate_audit(args: argparse.Namespace) -> dict[str, Any]:
    contract, run, solids = _require_run(args.project)
    sequence = contract.animation(args.sequence)
    result = audit_motion(sequence, solids)
    atomic_json(run.output("animations", args.sequence, "motion-audit.json"), result)
    return result


def _animate_prepare(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.project)
    return prepare_2_5d_package(contract, args.sequence, contract.project_dir / "presentation" / "animations" / args.sequence) | {"status": "PASS"}


def _present_prepare(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.project)
    return prepare_presentation(contract, contract.project_dir / "presentation" / "imagegen-package.json") | {"status": "PASS"}


def _accept(args: argparse.Namespace) -> dict[str, Any]:
    record = accept(load_contract(args.project), Path(args.image))
    return {"status": "PASS", **record}


def _reject(args: argparse.Namespace) -> dict[str, Any]:
    record = reject(load_contract(args.project), Path(args.image), args.reason)
    return {"status": "PASS", **record}


def _index_rebuild(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root()
    exports = [Path(item) for item in args.export]
    return rebuild_index(root, root / "governance" / "index.sqlite3", exports)


def _index_query(args: argparse.Namespace) -> list[dict[str, Any]]:
    return query_index(repo_root() / "governance" / "index.sqlite3", args.query, args.limit)


def _shield(args: argparse.Namespace) -> dict[str, Any]:
    return build_shield(load_contract(args.project), repo_root())


def _handoff(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.project)
    shield = build_shield(contract, repo_root())
    run = latest_run(contract)
    path = contract.project_dir / "HANDOFF.md"
    lines = ["# MVT Handoff", f"project: {contract.project_id}", f"contract_hash: {contract.hash}"]
    if run:
        lines += [f"run_id: {run.data['run_id']}", f"model_hash: {run.data.get('model_hash')}", f"status: {run.data['status']}"]
    lines += [f"compact_shield: {Path(shield['path']).name}", "next_action: Execute the next unmet RED/YELLOW gate; do not reinterpret accepted geometry from prose."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "PASS", "path": str(path)}


def _learn_ingest(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_json(Path(args.run) / "run-manifest.json")
    if not manifest:
        raise FileNotFoundError(args.run)
    events = []
    for finding in manifest.get("audit", {}).get("findings", []):
        if finding.get("status") == "RED":
            events.append({"type": "audit_failure", "gate": finding.get("gate"), "run_id": manifest["run_id"], "evidence": finding, "at": utc_now()})
    path = Path(args.run) / "events.json"
    atomic_json(path, events)
    return {"status": "PASS", "path": str(path), "events": len(events)}


def _kaizen_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    return evaluate_lesson(repo_root(), read_json(Path(args.lesson)))


def _kaizen_promote(args: argparse.Namespace) -> dict[str, Any]:
    return promote_lessons(repo_root(), [Path(item) for item in args.lesson] if args.lesson else None)


def _kaizen_rollback(args: argparse.Namespace) -> dict[str, Any]:
    return rollback_promotion(repo_root(), args.promotion_id, args.reason)


def _skill(args: argparse.Namespace) -> dict[str, Any]:
    target = Path(args.target).expanduser() if args.target else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills"
    return skill_action(resource_root(), args.action, target)


def _tool(args: argparse.Namespace) -> dict[str, Any]:
    if args.action in {"validate", "doctor"}:
        return validate_registry(repo_root())
    if args.action in {"enable", "disable"}:
        return set_enabled(repo_root(), args.name, args.action == "enable")
    if args.action == "init":
        path = repo_root() / "tools" / "definitions" / f"{args.name}.yaml"
        if path.exists():
            raise FileExistsError(path)
        path.write_text(yaml.safe_dump({"name": args.name, "version": "0.0.1", "entrypoint": "TODO", "side_effect": "read", "timeout_seconds": 30, "retry_limit": 0, "enabled": False, "healthcheck": "TODO", "skills": []}, sort_keys=False), encoding="utf-8")
        return {"status": "PASS", "path": str(path)}
    raise ValueError(args.action)


def _prompt(args: argparse.Namespace) -> dict[str, Any]:
    return {"build": build_prompt, "verify": verify_prompt, "rollback": rollback_prompt}[args.action](repo_root())


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mvt")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)

    doctor = subs.add_parser("doctor"); _add_json(doctor); doctor.set_defaults(func=_doctor)
    project = subs.add_parser("project").add_subparsers(dest="action", required=True)
    init = project.add_parser("init"); init.add_argument("slug"); init.add_argument("--template", choices=templates(), default="fixture-stage"); _add_json(init); init.set_defaults(func=_project_init)
    contract = subs.add_parser("contract").add_subparsers(dest="action", required=True)
    validate = contract.add_parser("validate"); validate.add_argument("project"); _add_json(validate); validate.set_defaults(func=_contract_validate)
    build = subs.add_parser("build"); build.add_argument("project"); build.add_argument("--no-step", action="store_true", help="Build/render geometry first; defer STEP export"); _add_json(build); build.set_defaults(func=_build)
    render = subs.add_parser("render"); render.add_argument("project"); render.add_argument("--set", default="proofs"); render.add_argument("--camera"); _add_json(render); render.set_defaults(func=_render)
    audit = subs.add_parser("audit"); audit.add_argument("project"); _add_json(audit); audit.set_defaults(func=_audit)

    workspace = subs.add_parser("workspace").add_subparsers(dest="action", required=True)
    workspace_init = workspace.add_parser("init"); workspace_init.add_argument("path"); _add_json(workspace_init); workspace_init.set_defaults(func=_workspace_init)
    step = subs.add_parser("step").add_subparsers(dest="action", required=True)
    inspect = step.add_parser("inspect"); inspect.add_argument("path"); _add_json(inspect); inspect.set_defaults(func=_step_inspect)
    drawing = step.add_parser("drawing"); drawing.add_argument("path"); drawing.add_argument("output"); drawing.add_argument("--title", default="Mechanical part"); _add_json(drawing); drawing.set_defaults(func=_step_drawing)

    animate = subs.add_parser("animate").add_subparsers(dest="action", required=True)
    for action, func in (("build", _animate_build), ("audit", _animate_audit), ("prepare", _animate_prepare)):
        item = animate.add_parser(action); item.add_argument("project"); item.add_argument("--sequence", required=True); _add_json(item); item.set_defaults(func=func)
    present = subs.add_parser("present").add_subparsers(dest="action", required=True)
    prep = present.add_parser("prepare"); prep.add_argument("project"); _add_json(prep); prep.set_defaults(func=_present_prepare)
    accepted = subs.add_parser("accept"); accepted.add_argument("project"); accepted.add_argument("image"); _add_json(accepted); accepted.set_defaults(func=_accept)
    rejected = subs.add_parser("reject"); rejected.add_argument("project"); rejected.add_argument("image"); rejected.add_argument("--reason", required=True); _add_json(rejected); rejected.set_defaults(func=_reject)
    shield = subs.add_parser("shield"); shield.add_argument("project"); _add_json(shield); shield.set_defaults(func=_shield)
    handoff = subs.add_parser("handoff"); handoff.add_argument("project"); _add_json(handoff); handoff.set_defaults(func=_handoff)

    index = subs.add_parser("index").add_subparsers(dest="action", required=True)
    rebuild = index.add_parser("rebuild"); rebuild.add_argument("--export", action="append", default=[]); _add_json(rebuild); rebuild.set_defaults(func=_index_rebuild)
    query = index.add_parser("query"); query.add_argument("query"); query.add_argument("--limit", type=int, default=10); _add_json(query); query.set_defaults(func=_index_query)
    learn = subs.add_parser("learn").add_subparsers(dest="action", required=True)
    ingest = learn.add_parser("ingest"); ingest.add_argument("run"); _add_json(ingest); ingest.set_defaults(func=_learn_ingest)
    kaizen = subs.add_parser("kaizen").add_subparsers(dest="action", required=True)
    evaluate = kaizen.add_parser("evaluate"); evaluate.add_argument("lesson"); _add_json(evaluate); evaluate.set_defaults(func=_kaizen_evaluate)
    promote = kaizen.add_parser("promote"); promote.add_argument("--lesson", action="append"); _add_json(promote); promote.set_defaults(func=_kaizen_promote)
    rollback = kaizen.add_parser("rollback"); rollback.add_argument("promotion_id"); rollback.add_argument("--reason", default="manual rollback"); _add_json(rollback); rollback.set_defaults(func=_kaizen_rollback)
    skill = subs.add_parser("skill"); skill.add_argument("action", choices=["install", "sync", "doctor", "uninstall"]); skill.add_argument("--target"); _add_json(skill); skill.set_defaults(func=_skill)
    tool = subs.add_parser("tool"); tool.add_argument("action", choices=["init", "validate", "enable", "disable", "doctor"]); tool.add_argument("name", nargs="?"); _add_json(tool); tool.set_defaults(func=_tool)
    prompt = subs.add_parser("prompt"); prompt.add_argument("action", choices=["build", "verify", "rollback"]); _add_json(prompt); prompt.set_defaults(func=_prompt)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = args.func(args)
        _result(data, args.json)
        return 5 if isinstance(data, dict) and data.get("status") == "RED" else 0
    except MVTError as exc:
        payload = {"status": "RED", "error": exc.code, "message": str(exc)}
        _result(payload, getattr(args, "json", False))
        return exc.exit_code
    except Exception as exc:
        payload = {"status": "RED", "error": exc.__class__.__name__, "message": str(exc)}
        _result(payload, getattr(args, "json", False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
