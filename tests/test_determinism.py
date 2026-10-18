from __future__ import annotations

from mvt.geometry.model import build_model, model_semantic_hash
from mvt.rendering.vtk_renderer import _polydata


def test_semantic_model_hash_is_repeatable(mechanics):
    first = model_semantic_hash(mechanics, build_model(mechanics))
    second = model_semantic_hash(mechanics, build_model(mechanics))
    assert first == second


def test_bbox_hash_does_not_change_after_tessellation(mechanics):
    solids = build_model(mechanics)
    before = model_semantic_hash(mechanics, solids)
    for solid in solids:
        _polydata(solid.shape)
    assert model_semantic_hash(mechanics, solids) == before
