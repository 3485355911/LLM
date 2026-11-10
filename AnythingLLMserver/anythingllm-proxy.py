"""AnythingLLM 上传页的本地代理：把 API Key 留在服务端，前端不再持有密钥。

作用：
1. `GET /` 返回 anythingllm-upload.html（同源，无需 CORS）
2. 把 `/api/**` 转发到 AnythingLLM 的 `/api/**`，由代理补上 `Authorization: Bearer ***`
3. 打一行访问日志（方法、路径、上游状态、耗时），不打印密钥

启动：
    set ANYTHINGLLM_API_KEY=你的开发者 API Key        # PowerShell: $env:ANYTHINGLLM_API_KEY="..."
    python anythingllm-proxy.py                       # 默认 http://127.0.0.1:8090

可选环境变量：
    ANYTHINGLLM_BASE_URL   上游地址，默认 http://127.0.0.1:3001
    PROXY_PORT             监听端口，默认 8090
    PROXY_HOST             监听地址，默认 127.0.0.1
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML_FILE = Path(__file__).with_name("anythingllm-upload.html")
UPSTREAM = os.environ.get("ANYTHINGLLM_BASE_URL", "http://127.0.0.1:3001").rstrip("/")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "").strip()
PORT = int(os.environ.get("PROXY_PORT", "8090"))
HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
TIMEOUT = 60

FORWARD_HEADERS = ("content-type", "accept")


class Handler(BaseHTTPRequestHandler):
    server_version = "anythingllm-proxy/1.0"

    def log_message(self, fmt: str, *args) -> None:  # 走自己的日志格式
        pass

    # ---- 路由 ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            return self._serve_html()
        if self.path == "/health":
            return self._send_json(200, b'{"ok": true, "upstream": "' + UPSTREAM.encode() + b'"}')
        if self.path.startswith("/api/"):
            return self._forward("GET")
        return self._send_text(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            return self._forward("POST")
        return self._send_text(404, "not found")

    def do_PUT(self) -> None:  # noqa: N802
        return self._forward("PUT") if self.path.startswith("/api/") else self._send_text(404, "not found")

    def do_DELETE(self) -> None:  # noqa: N802
        return self._forward("DELETE") if self.path.startswith("/api/") else self._send_text(404, "not found")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    # ---- 实现 ---------------------------------------------------------
    def _serve_html(self) -> None:
        try:
            body = HTML_FILE.read_bytes()
        except FileNotFoundError:
            return self._send_text(500, f"缺少页面文件：{HTML_FILE.name}")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, method: str) -> None:
        started = time.perf_counter()
        target = UPSTREAM + self.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {k: self.headers[k] for k in FORWARD_HEADERS if self.headers.get(k)}
        headers["Authorization"] = f"Bearer {API_KEY}"

        request = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                status = response.status
                payload = response.read()
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:  # 上游 4xx/5xx 原样回传，便于页面展示原因
            status = exc.code
            payload = exc.read() or b""
            content_type = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
        except Exception as exc:
            status = 502
            payload = ('{"error": "代理未能连接 AnythingLLM：%s"}' % type(exc).__name__).encode("utf-8")
            content_type = "application/json"

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        print(f"[proxy] {method} {self.path} -> {status} {elapsed}ms", file=sys.stderr, flush=True)

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    if not API_KEY:
        print(
            "未设置 ANYTHINGLLM_API_KEY。\n"
            "PowerShell：$env:ANYTHINGLLM_API_KEY=\"你的开发者 API Key\"\n"
            "然后重新运行：python anythingllm-proxy.py",
            file=sys.stderr,
        )
        return 2
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"页面已就绪： http://{HOST}:{PORT}/   上游： {UPSTREAM}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
