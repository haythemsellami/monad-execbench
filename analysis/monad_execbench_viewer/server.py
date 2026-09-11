from __future__ import annotations

import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from monad_execbench_report.results import parse_json, require

from .export import SCHEMA

# Packaged frontend assets: the page, ES modules, the stylesheet and the
# vendored fonts. Only these directories and suffixes are ever served.
ASSET_DIRECTORIES = ("", "views/", "fonts/")
ASSET_SUFFIXES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".html": "text/html; charset=utf-8",
}
ASSET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\.[a-z0-9]+")


def packaged_assets() -> dict[str, bytes]:
    """Read every servable asset into memory once; nothing is resolved per request."""
    static = files("monad_execbench_viewer").joinpath("static")
    assets: dict[str, bytes] = {}
    for prefix in ASSET_DIRECTORIES:
        folder = static.joinpath(prefix.rstrip("/")) if prefix else static
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            suffix = Path(entry.name).suffix
            if (
                entry.is_file()
                and ASSET_NAME.fullmatch(entry.name)
                and suffix in ASSET_SUFFIXES
            ):
                assets["/" + prefix + entry.name] = entry.read_bytes()
    require("/index.html" in assets, "viewer assets are missing index.html")
    return assets


def create_server(directory: Path, port: int = 0) -> ThreadingHTTPServer:
    directory = directory.resolve(strict=True)
    summary = parse_json((directory / "summary.json").read_bytes())
    require(
        isinstance(summary, dict) and summary.get("schema") == SCHEMA,
        "not a viewer-v1 export",
    )
    assets = packaged_assets()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host or self.headers.get("Origin") not in (
                None,
                f"http://{host}",
            ):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == "/":
                path = "/index.html"
            if path in assets:
                name = path[1:]
                payload = assets[path]
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
                ASSET_SUFFIXES.get(Path(name).suffix)
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
