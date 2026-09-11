from __future__ import annotations

import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from monad_execbench_report.results import parse_json, require

from .export import SCHEMA


def create_server(directory: Path, port: int = 0) -> ThreadingHTTPServer:
    directory = directory.resolve(strict=True)
    summary = parse_json((directory / "summary.json").read_bytes())
    require(
        isinstance(summary, dict) and summary.get("schema") == SCHEMA,
        "not a viewer-v1 export",
    )
    assets = files("monad_execbench_viewer").joinpath("static")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hosts = {f"127.0.0.1:{self.server.server_port}"}
            if self.server.server_port == 80:
                hosts.add("127.0.0.1")
            origins = {None, *(f"http://{host}" for host in hosts)}
            if (
                self.headers.get("Host") not in hosts
                or self.headers.get("Origin") not in origins
            ):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path in ("/", "/app.js", "/style.css"):
                name = "index.html" if path == "/" else path[1:]
                payload = assets.joinpath(name).read_bytes()
            elif path == "/summary.json" or re.fullmatch(
                r"/p[0-9]+-c[0-9]+(?:/frame-[0-9]+)?\.json", path
            ):
                name = path[1:]
                candidate = directory / name
                if (
                    not candidate.resolve().is_relative_to(directory)
                    or not candidate.is_file()
                    or any(p.is_symlink() for p in (candidate, candidate.parent))
                ):
                    self.send_error(404)
                    return
                payload = candidate.read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(name)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
