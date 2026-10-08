"""`python -m ops_mcp_write`: serve the write-tool server on 127.0.0.1:OPS_MCP_WRITE_PORT (default 8082)."""

from ops_mcp_write.server import serve

if __name__ == "__main__":
    serve()
