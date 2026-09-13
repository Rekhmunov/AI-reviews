"""stickers-print format=json must not break FastAPI app startup."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response


def test_stickers_print_union_return_annotation_is_avoided() -> None:
    """Regression: Response | dict crashes FastAPI at route registration → 502."""
    app = FastAPI()

    @app.get("/api/wb-fbs/supplies/{supply_id}/stickers-print")
    def stickers_print(format: str = "") -> Response:
        if str(format or "").strip().lower() == "json":
            return JSONResponse({"ok": True, "html": "<html/>", "cancelled_orders": []})
        return Response(content="<html/>", media_type="text/html; charset=utf-8")

    # If annotation were Response | dict, FastAPI would raise on decorator.
    assert any(
        getattr(r, "path", "") == "/api/wb-fbs/supplies/{supply_id}/stickers-print"
        for r in app.routes
    )


def test_web_py_does_not_use_response_dict_union() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "review_processor" / "web.py").read_text(
        encoding="utf-8"
    )
    assert "Response | dict[str, object]" not in src
    assert "return JSONResponse(" in src
    assert "cancelled_orders" in src
