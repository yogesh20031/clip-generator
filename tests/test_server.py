from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from viral_clipper import server
from viral_clipper.config import Config

EXPECTED_TOOLS = {
    "clip_video",
    "analyze_video",
    "score_moments",
    "generate_metadata",
    "set_clip_metadata",
    "list_outputs",
    "cut_clip",
    "story_map",
    "render_edit",
}


@pytest.fixture
async def client(test_config: Config):
    server.set_config(test_config)
    async with Client(server.mcp, raise_exceptions=True) as c:
        yield c
    server.set_config(None)


@pytest.mark.anyio
async def test_tool_list_and_schemas(client: Client) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    props = tools["clip_video"].input_schema["properties"]
    assert set(props) >= {"source", "niche", "num_clips", "min_len", "max_len", "platforms", "output_dir"}
    assert "ctx" not in props, "Context must be hidden from the model"


@pytest.mark.anyio
async def test_bad_inputs_become_tool_errors(client: Client, sample_video: Path) -> None:
    res = await client.call_tool("clip_video", {"source": str(sample_video), "niche": "nope"})
    assert res.is_error and "Unknown niche" in res.content[0].text
    res = await client.call_tool("analyze_video", {"source": "/definitely/not/here.mp4"})
    assert res.is_error and "does not exist" in res.content[0].text
    res = await client.call_tool("analyze_video", {"source": "https://www.youtube.com/watch?v=xxxxxxxxxxx"})
    assert res.is_error
    assert "unavailable" in res.content[0].text.lower() or "download" in res.content[0].text.lower()


@pytest.mark.anyio
async def test_end_to_end_clip_video(client: Client, sample_video: Path, test_config: Config) -> None:
    progress: list[float] = []

    async def on_progress(p: float, total: float | None, message: str | None) -> None:
        progress.append(p)

    res = await client.call_tool(
        "clip_video",
        {
            "source": str(sample_video),
            "niche": "gta6",
            "num_clips": 2,
            "min_len": 8,
            "max_len": 20,
            "platforms": ["tiktok", "youtube_shorts"],
        },
        progress_callback=on_progress,
    )
    assert not res.is_error, res.content[0].text
    data = res.structured_content
    assert 1 <= len(data["clips"]) <= 2
    assert progress and progress == sorted(progress)
    clip = data["clips"][0]
    assert Path(clip["path"]).exists() and Path(clip["thumbnail_path"]).exists()
    assert set(clip["metadata"]) == {"tiktok", "youtube_shorts"}
    assert Path(data["clips_json"]).exists() and Path(data["clips_csv"]).exists()
    assert Path(data["output_dir"]).parent == test_config.output_root

    listed = await client.call_tool("list_outputs", {})
    assert listed.structured_content["result"][0]["clip_count"] == len(data["clips"])

    meta = await client.call_tool(
        "generate_metadata", {"clip_path": clip["path"], "platform": "instagram_reels", "niche": "gta6"}
    )
    assert not meta.is_error and meta.structured_content["platform"] == "instagram_reels"

    saved = await client.call_tool(
        "set_clip_metadata",
        {
            "clip_path": clip["path"],
            "platform": "tiktok",
            "title": "My title",
            "description": "My desc",
            "hashtags": ["#gta6", "#fyp"],
            "hook": "WAIT",
        },
    )
    assert not saved.is_error
    listed = await client.call_tool("list_outputs", {})
    first = listed.structured_content["result"][0]["clips"][0]
    assert first["metadata"]["tiktok"]["title"] == "My title" and first["hook"] == "WAIT"


@pytest.mark.anyio
async def test_cut_clip_exact_range(client: Client, sample_video: Path) -> None:
    res = await client.call_tool(
        "cut_clip",
        {"source": str(sample_video), "start": "0:08", "duration": "12", "niche": "mrbeast", "hook": "MY HOOK"},
    )
    assert not res.is_error, res.content[0].text
    data = res.structured_content
    assert data["start"] == 8.0 and data["end"] == 20.0 and data["hook"] == "MY HOOK"
    assert Path(data["path"]).exists() and Path(data["path"]).with_suffix(".txt").exists()
    assert data["reasons"][0].startswith("manual cut")


@pytest.mark.anyio
async def test_render_edit_joins_segments(client: Client, sample_video: Path) -> None:
    res = await client.call_tool(
        "render_edit",
        {
            "source": str(sample_video),
            "segments": [["0:01", "0:05"], ["24", "28"]],
            "niche": "mrbeast",
            "hook": "Khalid vs Ronaldo for $1M",
        },
    )
    assert not res.is_error, res.content[0].text
    data = res.structured_content
    assert len(data["segments"]) == 2 and abs(data["duration"] - 8.0) < 0.2
    assert data["hook"] == "Khalid vs Ronaldo for $1M"
    sheet = Path(data["path"]).with_suffix(".txt").read_text(encoding="utf-8")
    assert "Edit list (2 pieces" in sheet


def test_parse_timestamp() -> None:
    from viral_clipper.pipeline import parse_timestamp

    assert parse_timestamp("17:42") == 1062.0
    assert parse_timestamp("1:20") == 80.0
    assert parse_timestamp("1:02:03") == 3723.0
    assert parse_timestamp("80.5") == 80.5 and parse_timestamp(80) == 80.0
