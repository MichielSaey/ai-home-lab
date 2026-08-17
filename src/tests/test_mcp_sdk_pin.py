from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIN = "mcp>=1.9,<2"


def test_garmin_mcp_pins_sdk_below_v2() -> None:
    text = (ROOT / "src/mcp-servers/garmin-mcp/requirements.txt").read_text()
    assert PIN in text.splitlines()


def test_ensure_odysseus_pins_sdk_below_v2() -> None:
    text = (ROOT / "scripts/ensure-odysseus.sh").read_text()
    assert f'ODYSSEUS_MCP_PIN="${{ODYSSEUS_MCP_PIN:-{PIN}}}"' in text
    assert "pin_odysseus_mcp_sdk" in text
