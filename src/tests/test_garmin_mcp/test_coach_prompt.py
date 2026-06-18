import sys
from pathlib import Path

GARMIN_MCP_DIR = Path(__file__).resolve().parents[3] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))

import server  # noqa: E402


def test_load_coach_prompt_returns_80_20_guidance() -> None:
    prompt = server._load_coach_prompt()

    assert "80/20" in prompt
    assert "polarized" in prompt.lower()


def test_coach_prompt_resource_aliases_loader() -> None:
    assert server.coach_prompt() == server._load_coach_prompt()
