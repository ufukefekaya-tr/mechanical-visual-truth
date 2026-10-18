from __future__ import annotations

import copy

from mvt.auditing import audit_contract_model
from mvt.geometry import build_model
from conftest import changed


def test_generic_counts_and_topology_pass(mechanics):
    result = audit_contract_model(mechanics, build_model(mechanics))
    assert result["status"] == "PASS", result["findings"]
    assert result["class_counts"]["payload"] == 1
    assert result["physical_status"] == result["safety_status"] == "YELLOW"
    assert any(item["gate"] == "clearance" and item["method"] == "brep" for item in result["findings"])


def test_forbidden_class_is_red(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["entities"].append({"id": "bad-support", "class": "obsolete_support", "primitive": "box", "position": [0,20,0], "size": [10,2,2], "material": "steel"})
    contract = changed(mechanics, data)
    result = audit_contract_model(contract, build_model(contract))
    assert any(item["gate"] == "forbidden-geometry" and item["status"] == "RED" for item in result["findings"])


def test_wrong_count_and_placement_are_red(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["entities"] = [item for item in data["entities"] if item["id"] != "guide"]
    next(item for item in data["entities"] if item["id"] == "payload")["station"] = "park"
    contract = changed(mechanics, data)
    result = audit_contract_model(contract, build_model(contract))
    assert any(item.get("class") == "guide" and item["status"] == "RED" for item in result["findings"])
    assert any(item["gate"] == "placement" and item["status"] == "RED" for item in result["findings"])


def test_concept_extension_is_yellow_but_same_geometry_fails_strict_tier(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["project"]["validation_tier"] = "concept_visual"
    data["entities"][0]["position"] = [60,0,0]
    data["entities"][0]["metadata"] = {"candidate_envelope_only": True}
    contract = changed(mechanics, data)
    concept = audit_contract_model(contract, build_model(contract))
    assert concept["status"] == concept["concept_status"] == "YELLOW"
    data["project"]["validation_tier"] = "geometry"
    strict = changed(mechanics, data)
    assert audit_contract_model(strict, build_model(strict))["status"] == "RED"


def test_explicit_envelope_origin_does_not_assume_ground_plane(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["envelope_origin"] = [-50,-40,-5]
    contract = changed(mechanics, data)
    result = audit_contract_model(contract, build_model(contract))
    assert any(item["gate"] == "envelope" and "base" in item["outside"] for item in result["findings"])


def test_missing_built_entity_fails_coverage(mechanics):
    solids = build_model(mechanics)
    result = audit_contract_model(mechanics, solids[1:])
    assert any(item["gate"] == "entity-coverage" and item["status"] == "RED" for item in result["findings"])
