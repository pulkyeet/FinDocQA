"""FastAPI app factory for FinDocQA Delta web server."""

import os
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
_TEMPLATES_DIR = os.path.join(_WEB_DIR, "templates")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")


def create_app() -> FastAPI:
    app = FastAPI(title="FinDocQA Delta")

    if os.path.isdir(_STATIC_DIR):
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    from web.routes import register_routes
    register_routes(app, templates, _SRC_DIR)

    return app


app = create_app()
