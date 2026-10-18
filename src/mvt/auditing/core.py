"""Nominal B-rep verification and explicit validation scope.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

from collections import Counter
import math
from typing import Any

from mvt.contracts import Contract
from mvt.geometry import EntitySolid


def _distance(a: dict[str, list[float]], b: dict[str, list[float]]) -> float:
    """AABB lower bound, used only to reject unnecessary narrow-phase work."""
    return math.sqrt(sum(max(a["min"][i]-b["max"][i], b["min"][i]-a["max"][i], 0.0)**2 for i in range(3)))


def geometry_pair(a: EntitySolid, b: EntitySolid) -> dict[str, float]:
    """Nominal B-rep checks. Bounding boxes cannot prove interference."""
    distance = float(a.shape.distance(b.shape))
    intersection = 0.0
    if _distance(a.bbox, b.bbox) <= 1e-7:
        common = a.shape.intersect(b.shape)
        # OCC's generic Volume() returns inappropriate values for an empty
        # lower-dimensional intersection. Only solid components count here.
        intersection = sum(abs(solid.Volume()) for solid in common.Solids())
    if not math.isfinite(distance) or not math.isfinite(intersection):
        raise ValueError("Nonfinite B-rep pair result")
    return {"distance_mm": max(0.0, distance), "intersection_mm3": intersection}


def result_status(findings: list[dict[str, Any]]) -> str:
    return "RED" if any(item["status"] == "RED" for item in findings) else "YELLOW" if any(item["status"] == "YELLOW" for item in findings) else "PASS"


def audit_contract_model(contract: Contract, solids: list[EntitySolid]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    counts = Counter(item.entity_class for item in solids)
    counts["station"] = len(contract.data.get("stations", []))
    ids = [item.id for item in solids]
    findings.append({"gate": "entity-identity", "status": "PASS" if len(ids) == len(set(ids)) else "RED"})
    required_ids = {item["id"] for item in contract.entities if item.get("visible", True)}
    findings.append({"gate": "entity-coverage", "missing": sorted(required_ids-set(ids)), "unexpected": sorted(set(ids)-required_ids), "status": "PASS" if required_ids == set(ids) else "RED"})
    invalid = [item.id for item in solids if not item.shape.isValid() or len(item.shape.Solids()) != 1 or item.shape.Volume() <= 1e-9]
    findings.append({"gate": "brep-validity", "invalid": invalid, "status": "RED" if invalid else "PASS"})
    requirements = contract.data.get("requirements", {})
    for entity_class, expected in requirements.get("counts", {}).items():
        actual = counts.get(entity_class, 0)
        findings.append({"gate": "count", "class": entity_class, "expected": expected, "actual": actual, "status": "PASS" if actual == expected else "RED"})
    by_id = {item.id: item for item in solids}
    for rule in requirements.get("placements", []):
        allowed = set(rule.get("allowed_stations", []))
        bad = [item.id for item in solids if item.entity_class == rule["class"] and item.station not in allowed]
        findings.append({"gate": "placement", "class": rule["class"], "invalid": bad, "status": "RED" if bad else "PASS"})
    for rule in requirements.get("forbidden_geometry", []):
        selected = [item.id for item in solids if item.entity_class == rule["class"]]
        findings.append({"gate": "forbidden-geometry", "rule": rule.get("id"), "class": rule["class"], "actual": len(selected), "entities": selected, "status": "PASS" if len(selected) <= rule.get("max_count", 0) else "RED"})
    envelope = contract.data["envelope"]
    origin = contract.data.get("envelope_origin", [-size/2 for size in envelope])
    outside, extensions = [], []
    concept = contract.data["project"].get("validation_tier") == "concept_visual"
    for item in solids:
        box = item.bbox
        if any(box["min"][axis] < origin[axis]-0.01 or box["max"][axis] > origin[axis]+envelope[axis]+0.01 for axis in range(3)):
            (extensions if concept and item.metadata.get("candidate_envelope_only") is True else outside).append(item.id)
    envelope_result: dict[str, Any] = {"gate": "envelope", "origin": origin, "outside": outside, "status": "RED" if outside else "YELLOW" if extensions else "PASS"}
    if extensions:
        envelope_result.update({"outside_service_candidates": extensions, "reason": "Declared concept extensions exceed the envelope; deployed footprint remains unverified."})
    findings.append(envelope_result)
    for rule in requirements.get("clearances", []):
        a, b = by_id.get(rule["a"]), by_id.get(rule["b"])
        if a is None or b is None:
            findings.append({"gate": "clearance", "rule": rule.get("id"), "status": "RED", "reason": "unknown or hidden entity"})
            continue
        try:
            pair = geometry_pair(a, b)
            passed = pair["distance_mm"]+1e-6 >= rule["minimum"] and pair["intersection_mm3"] <= 1e-7
            findings.append({"gate": "clearance", "rule": rule.get("id"), "minimum": rule["minimum"], "actual": pair["distance_mm"], "method": "brep", **pair, "status": "PASS" if passed else "RED"})
        except Exception as exc:
            findings.append({"gate": "clearance", "rule": rule.get("id"), "status": "RED", "reason": "B-rep evaluation failed", "detail": type(exc).__name__})
    for pair_ids in requirements.get("collision_pairs", []):
        try:
            pair = geometry_pair(by_id[pair_ids[0]], by_id[pair_ids[1]])
            findings.append({"gate": "collision", "entities": pair_ids, "method": "brep", **pair, "status": "RED" if pair["intersection_mm3"] > 1e-7 else "PASS"})
        except Exception as exc:
            findings.append({"gate": "collision", "entities": pair_ids, "status": "RED", "reason": "B-rep evaluation failed or entity missing", "detail": type(exc).__name__})
    tier = contract.data["project"].get("validation_tier", "geometry")
    status = result_status(findings)
    warnings = ["Commercial envelopes are not vendor-verified."] if contract.data.get("commercial_status") == "commercially_unverified" or any("commercially_unverified" in (item.metadata.get("commercial_status"), item.metadata.get("status")) for item in solids) else []
    return {
        "status": status, "validation_tier": tier,
        "concept_status": status if tier == "concept_visual" else "NOT_REQUESTED",
        "geometry_status": status, "physical_status": "YELLOW", "safety_status": "YELLOW",
        "contract_hash": contract.hash, "entity_count": len(solids),
        "class_counts": dict(sorted(counts.items())), "findings": findings, "warnings": warnings,
        "limitations": ["Nominal CAD geometry and declared rules only; no load, tolerance, manufacturing, hardware or safety qualification.", "Only declared static entity pairs are checked for clearance/interference."],
    }
