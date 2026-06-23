import sys
from pathlib import Path

GARMIN_MCP_DIR = Path(__file__).resolve().parents[2] / "mcp-servers" / "garmin-mcp"
sys.path.insert(0, str(GARMIN_MCP_DIR))
