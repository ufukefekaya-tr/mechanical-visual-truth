from __future__ import annotations

import copy
import json

import cadquery as cq
import pytest

from conftest import changed
from mvt.errors import BuildError
from mvt.geometry import build_model
from mvt.geometry.model import _primitive, _pose, optimal_bbox
from mvt.util import sha256_file


def source_contract(mechanics, count=1, with_sidecar=False):
    path = mechanics.project_dir / "native.step"
    shapes = [cq.Workplane("XY").box(10,6,4).val().translate((20*index,0,0)) for index in range(count)]
    cq.exporters.export(cq.Compound.makeCompound(shapes), str(path), "STEP")
    source = {"id": "native", "path": "native.step", "sha256": sha256_file(path), "format": "STEP"}
    if with_sidecar:
        imported = cq.importers.importStep(str(path)).solids().vals()
        sidecar_path = mechanics.project_dir / "native.json"
        sidecar = {"source_sha256": source["sha256"], "actors": [
            {"id": f"part.{index}", "solid_index": index, "signature": {"bbox": optimal_bbox(shape), "volume_mm3": shape.Volume()}}
            for index, shape in enumerate(imported)]}
        sidecar_path.write_text(json.dumps(sidecar))
        source.update(sidecar_path="native.json", sidecar_sha256=sha256_file(sidecar_path))
    data = copy.deepcopy(mechanics.data)
    data["sources"] = [source]
    data["entities"] = [{"id": "imported", "class": "part", "source_id": "native", "position": [0,0,0], "material": "steel"}]
    if with_sidecar:
        data["entities"][0]["source_actor_id"] = "part.0"
    return changed(mechanics, data)


def test_single_step_is_hash_locked_and_contract_owned(mechanics):
    contract = source_contract(mechanics)
    solids = build_model(contract)
    assert len(solids) == 1
    assert solids[0].shape.Volume() == pytest.approx(240)
    assert solids[0].metadata["source"]["sha256"] == contract.data["sources"][0]["sha256"]
    (mechanics.project_dir / "native.step").write_text("changed")
    with pytest.raises(BuildError, match="Source hash mismatch"):
        build_model(contract)


def test_multi_solid_source_requires_sidecar(mechanics):
    contract = source_contract(mechanics, count=2)
    with pytest.raises(BuildError, match="requires a hash-locked sidecar"):
        build_model(contract)


def test_sidecar_selects_stable_native_actor(mechanics):
    contract = source_contract(mechanics, count=2, with_sidecar=True)
    data = copy.deepcopy(contract.data)
    data["entities"][0]["source_actor_id"] = "part.1"
    assert build_model(changed(contract, data))[0].bbox["min"][0] == pytest.approx(15)


def test_sidecar_detects_wrong_binding_even_when_its_own_hash_updated(mechanics):
    contract = source_contract(mechanics, count=2, with_sidecar=True)
    path = mechanics.project_dir / "native.json"
    sidecar = json.loads(path.read_text())
    sidecar["actors"][0]["signature"]["volume_mm3"] *= 2
    path.write_text(json.dumps(sidecar))
    data = copy.deepcopy(contract.data)
    data["sources"][0]["sidecar_sha256"] = sha256_file(path)
    with pytest.raises(BuildError, match="Source signature mismatch"):
        build_model(changed(contract, data))


def test_brep_sources_use_same_contract_ownership(mechanics):
    path = mechanics.project_dir / "native.brep"
    cq.Workplane("XY").box(4,5,6).val().exportBrep(str(path))
    data = copy.deepcopy(mechanics.data)
    data["sources"] = [{"id": "brep", "path": path.name, "sha256": sha256_file(path), "format": "BREP"}]
    data["entities"] = [{"id": "native", "class": "part", "source_id": "brep", "position": [0,0,0], "material": "steel"}]
    assert build_model(changed(mechanics, data))[0].shape.Volume() == pytest.approx(120)


def test_local_cut_precedes_world_rotation(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["entities"] = [{"id": "drilled", "class": "part", "primitive": "box", "size": [20,10,6], "position": [10,15,0], "rotation": [0,0,90], "material": "steel",
        "cuts": [{"primitive": "cylinder", "radius": 2, "height": 8, "position": [5,0,0]}]}]
    solid = build_model(changed(mechanics, data))[0]
    assert solid.shape.Volume() == pytest.approx(1200-24*3.141592653589793)
    assert solid.bbox["min"] == pytest.approx([5,5,-3])
    hole_point = cq.Vector(10,20,0)
    assert not solid.shape.isInside(hole_point)


def test_non_intersecting_cut_fails(mechanics):
    data = copy.deepcopy(mechanics.data)
    data["entities"][0]["cuts"] = [{"primitive": "box", "size": [1,1,1], "position": [1000,0,0]}]
    with pytest.raises(BuildError, match="ineffective cut"):
        build_model(changed(mechanics, data))


def test_hex_prism_bore_is_real_geometry(mechanics):
    shape = _primitive({"primitive": "hex_prism", "across_flats": 12, "height": 5, "bore_radius": 2})
    assert shape.isValid() and len(shape.Solids()) == 1
    assert not shape.isInside(cq.Vector(0,0,0))


def test_load_contract_checks_source_hash_before_any_cad_import(mechanics):
    import yaml
    from mvt.contracts import load_contract
    from mvt.errors import ContractError

    contract = source_contract(mechanics)
    data = copy.deepcopy(contract.data)
    data["requirements"] = {}
    data["animations"] = []
    contract.path.write_text(yaml.safe_dump(data))
    assert load_contract(contract.path).data["sources"]
    (mechanics.project_dir / "native.step").write_text("changed")
    with pytest.raises(ContractError, match="Source hash mismatch"):
        load_contract(contract.path)
