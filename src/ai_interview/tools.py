from pathlib import Path

from .mcp_server import MCPServer

SKILL_DIR = Path(__file__).resolve().parent / "tool_skills"


def create_server() -> MCPServer:
    server = MCPServer()
    server.register_skill_directory(SKILL_DIR)
    return server


server = create_server()
