"""FastAPI app factory for the Delta web server."""

import os
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import DELTA_REPORTS_DIR

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
_TEMPLATES_DIR = os.path.join(_WEB_DIR, "templates")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")


def create_app() -> FastAPI:
    app = FastAPI(title="Delta")

    if os.path.isdir(_STATIC_DIR):
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # Serve the built reports directly too, so A/B variants and other
    # non-canonical filenames are reachable without a route per file.
    reports_dir = os.path.join(_SRC_DIR, DELTA_REPORTS_DIR)
    if os.path.isdir(reports_dir):
        app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")

    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    templates.env.globals["static_v"] = static_version

    from web.routes import register_routes
    register_routes(app, templates, _SRC_DIR)

    return app


def static_version(rel_path: str) -> str:
    """Cache-busting token for a /static asset: its mtime.

    Browsers cache CSS and images aggressively; without this, a redeployed
    stylesheet can render as if nothing changed until the user hard-refreshes.
    """
    path = os.path.join(_STATIC_DIR, rel_path)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


app = create_app()
