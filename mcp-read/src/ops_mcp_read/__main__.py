"""`python -m ops_mcp_read`: serve the read-tool server on 127.0.0.1:OPS_MCP_READ_PORT (default 8081)."""

from ops_mcp_read.server import serve

if __name__ == "__main__":
    serve()
