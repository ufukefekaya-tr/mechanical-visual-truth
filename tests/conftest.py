from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from mvt.contracts import Contract, load_contract
from mvt.util import sha256_data


@pytest.fixture
def repo() -> Path:
    return Path(__file__).resolve().parents[1]


def synthetic_contract() -> dict:
    """Small invented mechanism; no project/customer geometry is used in tests."""
    return {
        "project": {"id": "synthetic-mechanism", "revision": "r1", "units": "mm", "validation_tier": "geometry"},
        "coordinate_system": {"x": "travel", "y": "width", "z": "up"},
        "envelope": [100, 80, 60],
        "stations": [{"id": "work", "x": 0}, {"id": "park", "x": 30}],
        "entities": [
            {"id": "base", "class": "base", "primitive": "box", "position": [0,0,-10], "size": [60,40,4], "material": "paint_blue", "color": [0.12,0.32,0.58]},
            {"id": "carriage", "class": "carriage", "primitive": "box", "position": [0,0,0], "size": [12,8,8], "station": "work", "material": "steel"},
            {"id": "payload", "class": "payload", "primitive": "box", "position": [0,0,6], "size": [4,4,4], "station": "work", "material": "polymer", "color": [0.85,0.45,0.12]},
            {"id": "guide", "class": "guide", "primitive": "cylinder", "position": [20,0,0], "radius": 2, "height": 30, "material": "steel"},
        ],
        "requirements": {
            "counts": {"base": 1, "carriage": 1, "payload": 1, "guide": 1, "station": 2},
            "placements": [{"class": "payload", "allowed_stations": ["work"]}],
            "forbidden_geometry": [{"id": "no-extra-support", "class": "obsolete_support", "max_count": 0}],
            "clearances": [{"id": "guide-gap", "a": "carriage", "b": "guide", "minimum": 10}],
            "collision_pairs": [["carriage", "guide"]],
        },
        "cameras": [{"id": "isometric", "position": [100,-120,90], "focal_point": [0,0,0], "up": [0,0,1], "projection": "parallel", "parallel_scale": 40, "size": [320,240]}],
        "animations": [{
            "id": "transfer", "truth_mode": "deterministic_cad", "camera": "isometric", "fps": 2, "duration": 1,
            "coupled_groups": [["carriage", "payload"]], "collision_pairs": [["carriage", "guide"]],
            "keyframes": [{"entity": actor, "t": t, "translation": [10*t,0,0]} for actor in ("carriage", "payload") for t in (0,1)],
        }, {
            "id": "presentation-transfer", "truth_mode": "presentation_only_2_5d", "camera": "isometric", "fps": 2, "duration": 1,
            "keyframes": [{"entity": "carriage", "t": t, "translation": [10*t,0,0]} for t in (0,1)],
        }],
    }


@pytest.fixture
def mechanics(tmp_path: Path) -> Contract:
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump(synthetic_contract(), sort_keys=False), encoding="utf-8")
    return load_contract(path)


@pytest.fixture
def bridge(mechanics: Contract) -> Contract:
    """Compatibility alias for acceptance/governance tests; data is synthetic."""
    return mechanics


def changed(contract: Contract, data: dict) -> Contract:
    value = copy.deepcopy(data)
    return Contract(contract.path, value, sha256_data(value))
