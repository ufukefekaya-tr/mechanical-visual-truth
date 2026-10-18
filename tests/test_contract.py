from __future__ import annotations

import copy

import pytest

from mvt.contracts import validate_contract
from mvt.contracts.loader import source_path
from mvt.errors import ContractError


def test_synthetic_contract_is_valid(mechanics):
    assert validate_contract(mechanics.data) == []
    assert mechanics.camera("isometric")["projection"] == "parallel"


@pytest.mark.parametrize("vector", [[1,2], [1,2,3,4], [1,0,0]])
def test_sizes_have_three_strictly_positive_components(mechanics, vector):
    data = copy.deepcopy(mechanics.data)
    data["entities"][0]["size"] = vector
    assert validate_contract(data)


def test_nonfinite_numbers_rejected(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["entities"][0]["position"][0] = float("nan")
    assert any("finite" in error for error in validate_contract(data))


def test_duplicate_entity_and_animation_ids_rejected(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["entities"].append(copy.deepcopy(data["entities"][0]))
    data["animations"].append(copy.deepcopy(data["animations"][0]))
    errors = validate_contract(data)
    assert "entities: IDs must be unique" in errors
    assert "animations: IDs must be unique" in errors


def test_duplicate_keyframe_time_rejected(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["animations"][0]["keyframes"].append(copy.deepcopy(data["animations"][0]["keyframes"][0]))
    assert any("duplicate keyframe time" in error for error in validate_contract(data))


def test_source_paths_belong_to_contract_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.step"
    outside.write_text("not geometry")
    (root / "linked.step").symlink_to(outside)
    for value in (str(outside), "../outside.step", "linked.step"):
        with pytest.raises(ContractError):
            source_path(root, value)


def test_camera_cannot_look_along_up_vector(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["cameras"][0].update(position=[0,0,10], up=[0,0,1])
    assert any("nonparallel" in error for error in validate_contract(data))


def test_unknown_collision_entity_rejected(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["animations"][0]["collision_pairs"] = [["carriage", "missing"]]
    assert any("unknown" in error for error in validate_contract(data))


@pytest.mark.parametrize("identifier", ["../escape", "..", ".hidden", "/tmp/outside"])
def test_camera_and_animation_ids_are_safe_path_components(mechanics, identifier):
    data = copy.deepcopy(mechanics.data)
    data["cameras"][0]["id"] = identifier
    assert validate_contract(data)
    data = copy.deepcopy(mechanics.data)
    data["animations"][0]["id"] = identifier
    assert validate_contract(data)
