"""支持 `python -m mcp_server` 直接启动（默认 stdio 传输）。"""

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
