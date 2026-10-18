from __future__ import annotations

import asyncio
import json
import sys

import pytest

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mvt.mcp_server import Workspace, build_server


def value(result):
    content = getattr(result, "structured_content", None)
    return content if content is not None else json.loads(result.content[0].text)


def test_stdio_protocol_and_contract_lifecycle(tmp_path):
    async def scenario():
        parameters = StdioServerParameters(command=sys.executable,
            args=["-I", "-m", "mvt.mcp_server", "--workspace", str(tmp_path)])
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                assert {t.name for t in listing.tools} >= {
                    "mvt_model_build", "mvt_step_inspect", "mvt_step_drawing", "mvt_artifact_preview"}
                created = await session.call_tool("mvt_project_create", {"project": "public-test"})
                assert not created.is_error
                assert value(created)["status"] == "PASS"
                checked = await session.call_tool("mvt_contract_validate", {"project": "public-test"})
                assert not checked.is_error
                assert value(checked)["status"] == "PASS"
                readback = value(await session.call_tool("mvt_contract_read", {"project": "public-test"}))
                contract = readback["contract"]
                contract["project"]["revision"] = "r2"
                stale = await session.call_tool("mvt_contract_write", {
                    "project": "public-test", "contract": contract, "expected_hash": "stale"})
                assert stale.is_error
                saved = await session.call_tool("mvt_contract_write", {
                    "project": "public-test", "contract": contract, "expected_hash": readback["contract_hash"]})
                assert not saved.is_error
                assert value(saved)["contract_hash"] != readback["contract_hash"]
                escape = await session.call_tool("mvt_contract_read", {"project": "../outside"})
                assert escape.is_error
                duplicate = await session.call_tool("mvt_project_create", {"project": "public-test"})
                assert duplicate.is_error
    asyncio.run(scenario())


def test_workspace_rejects_absolute_traversal_and_symlink(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (root / "link").symlink_to(foreign, target_is_directory=True)
    workspace = Workspace(root)
    for path in ("../foreign", str(foreign), "link/item", ".git/config"):
        with pytest.raises(ValueError):
            workspace.path(path, must_exist=False)


def test_mcp_annotations_and_read_only_inventory(tmp_path):
    async def scenario():
        server = build_server(tmp_path)
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert len(tools) == 13
        assert tools["mvt_contract_read"].annotations.read_only_hint is True
        assert tools["mvt_model_build"].annotations.read_only_hint is False
        assert all(not t.annotations.open_world_hint for t in tools.values())
    asyncio.run(scenario())
