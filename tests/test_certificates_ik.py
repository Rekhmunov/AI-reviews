"""Certificate annual IK (инспекционный контроль) helpers — source + pure parse checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def _parse_certificate_ik_dates(raw: Any) -> list[dict[str, Any]]:
    """Local copy of Repository._parse_certificate_ik_dates for offline unit checks."""
    if raw is None:
        return []
    data = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year"))
        except (TypeError, ValueError):
            continue
        date_s = str(item.get("date") or "").strip()[:10]
        if year < 1990 or year > 2100 or len(date_s) != 10:
            continue
        if year in seen_years:
            continue
        seen_years.add(year)
        out.append({"year": year, "date": date_s})
    out.sort(key=lambda x: int(x["year"]))
    return out


def test_repo_has_ik_column_and_methods() -> None:
    assert "ik_dates_json" in REPO_PY
    assert "def set_certificate_ik_date" in REPO_PY
    assert "def _parse_certificate_ik_dates" in REPO_PY
    assert "d[\"ik_dates\"] = ik_dates" in REPO_PY or "d['ik_dates'] = ik_dates" in REPO_PY


def test_api_has_ik_endpoint() -> None:
    assert '"/api/certificates/{cert_id}/ik"' in WEB_PY
    assert "class CertificateIkDateRequest" in WEB_PY


def test_parse_ik_dates_normalizes_and_dedupes() -> None:
    raw = [
        {"year": 2026, "date": "2026-09-15"},
        {"year": 2025, "date": "2025-09-10"},
        {"year": 2026, "date": "2026-10-01"},
        {"year": "bad", "date": "2024-01-01"},
        {"year": 2024, "date": "bad"},
    ]
    assert _parse_certificate_ik_dates(raw) == [
        {"year": 2025, "date": "2025-09-10"},
        {"year": 2026, "date": "2026-09-15"},
    ]


def test_parse_ik_dates_from_json_string() -> None:
    assert _parse_certificate_ik_dates('[{"year": 2026, "date": "2026-09-20"}]') == [
        {"year": 2026, "date": "2026-09-20"}
    ]


def test_parse_ik_dates_empty() -> None:
    assert _parse_certificate_ik_dates(None) == []
    assert _parse_certificate_ik_dates("") == []
    assert _parse_certificate_ik_dates("{}") == []
