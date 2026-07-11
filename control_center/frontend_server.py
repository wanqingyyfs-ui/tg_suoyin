from __future__ import annotations

import functools
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .runtime import WEB_DIST_DIR, apply_env


class FrontendHandler(SimpleHTTPRequestHandler):
    server_version = "tg-suoyin-frontend/1.0"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        print("前端访问：" + (fmt % args), flush=True)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/healthz":
            payload = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


def serve() -> None:
    env = apply_env()
    host = env.get("FRONTEND_HOST", "127.0.0.1") or "127.0.0.1"
    try:
        port = int(env.get("FRONTEND_PORT", "4321") or 4321)
    except ValueError:
        port = 4321
    root = Path(WEB_DIST_DIR)
    index = root / "index.html"
    if not index.exists():
        raise SystemExit(f"❌ 前端构建不存在：{index}。请先在控制中心点击‘构建前端’。")
    handler = functools.partial(FrontendHandler, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    print(f"✅ 前端服务已启动：http://{host}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("已停止前端服务。", flush=True)


if __name__ == "__main__":
    serve()
