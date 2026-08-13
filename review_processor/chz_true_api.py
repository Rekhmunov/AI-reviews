"""Chestny Znak (ГИС МТ) True API client — auth challenge + documents."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode


PROD_BASE = "https://markirovka.crpt.ru/api/v3/true-api"
DEMO_BASE = "https://markirovka.sandbox.crpt.tech/api/v3/true-api"


class ChzTrueApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ChzTrueApiClient:
    def __init__(self, *, base_url: str = "", timeout: int = 45) -> None:
        raw = str(base_url or "").strip().rstrip("/")
        if raw.endswith("/api/v3/true-api"):
            self.base = raw
        elif "sandbox" in raw or "demo" in raw:
            self.base = DEMO_BASE
        elif raw:
            self.base = raw
        else:
            self.base = PROD_BASE
        self.timeout = timeout
        self.token = ""

    def set_token(self, token: str) -> None:
        self.token = str(token or "").strip()

    def _url(self, path: str, params: dict[str, object] | None = None) -> str:
        p = path if path.startswith("/") else f"/{path}"
        qs = ""
        if params:
            qs = "?" + urlencode({k: v for k, v in params.items() if v is not None})
        return f"{self.base}{p}{qs}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | list[object] | None = None,
        auth: bool = True,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "User-Agent": "FeedPilot-CHZ/1.0",
        }
        if auth:
            if not self.token:
                raise ChzTrueApiError("Нет токена True API — сначала авторизуйтесь")
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(
            self._url(path, params),
            method=method.upper(),
            headers=headers,
            data=data,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                if not payload:
                    return {}
                return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:800]
            except Exception:
                pass
            raise ChzTrueApiError(
                f"ЧЗ True API HTTP {exc.code}: {err_body or exc.reason}",
                status=int(exc.code),
                body=err_body,
            ) from exc
        except urllib.error.URLError as exc:
            raise ChzTrueApiError(f"ЧЗ True API сеть: {exc.reason}") from exc

    def auth_key(self) -> dict[str, str]:
        data = self._request("GET", "/auth/key", auth=False)
        if not isinstance(data, dict):
            raise ChzTrueApiError("Некорректный ответ /auth/key")
        uuid = str(data.get("uuid") or "").strip()
        challenge = str(data.get("data") or "").strip()
        if not uuid or not challenge:
            raise ChzTrueApiError("В ответе /auth/key нет uuid/data")
        return {"uuid": uuid, "data": challenge}

    def simple_sign_in(
        self,
        *,
        uuid: str,
        signature_b64: str,
        inn: str = "",
        united_token: bool = False,
    ) -> str:
        body: dict[str, object] = {
            "uuid": str(uuid or "").strip(),
            "data": str(signature_b64 or "").strip().replace("\n", "").replace("\r", ""),
        }
        inn_s = str(inn or "").strip()
        if inn_s:
            body["inn"] = inn_s
        if united_token:
            body["unitedToken"] = True
        data = self._request("POST", "/auth/simpleSignIn", body=body, auth=False)
        if not isinstance(data, dict):
            raise ChzTrueApiError("Некорректный ответ /auth/simpleSignIn")
        token = str(data.get("token") or data.get("access_token") or "").strip()
        if not token:
            raise ChzTrueApiError("Токен не получен из /auth/simpleSignIn")
        self.set_token(token)
        return token

    def create_document(
        self,
        *,
        doc_type: str,
        product_group: str,
        product_document: dict[str, Any],
        signature_b64: str,
        document_format: str = "MANUAL",
    ) -> str:
        """Create LK_RECEIPT / LP_RETURN. Returns document id."""
        raw = json.dumps(product_document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        product_b64 = base64.b64encode(raw).decode("ascii")
        body = {
            "document_format": document_format,
            "product_document": product_b64,
            "type": str(doc_type or "").strip(),
            "signature": str(signature_b64 or "").strip().replace("\n", "").replace("\r", ""),
        }
        pg = str(product_group or "").strip()
        params: dict[str, object] = {"type": body["type"]}
        if pg:
            params["pg"] = pg
        data = self._request(
            "POST",
            "/lk/documents/create",
            params=params,
            body=body,
            auth=True,
        )
        if isinstance(data, str) and data.strip():
            return data.strip()
        if isinstance(data, dict):
            for key in ("id", "documentId", "document_id", "number"):
                val = data.get(key)
                if val:
                    return str(val)
            # Some stands return bare uuid as JSON string already handled above.
            if len(data) == 1:
                only = next(iter(data.values()))
                if only:
                    return str(only)
        raise ChzTrueApiError(f"Не удалось разобрать id документа: {data!r}")

    def document_info(self, document_id: str) -> dict[str, Any]:
        doc_id = str(document_id or "").strip()
        if not doc_id:
            raise ChzTrueApiError("Пустой document_id")
        data = self._request("GET", f"/doc/{doc_id}/info", auth=True)
        return data if isinstance(data, dict) else {"raw": data}

    def cises_info(self, codes: list[str]) -> list[dict[str, Any]]:
        cleaned = [str(c or "").strip() for c in codes if str(c or "").strip()]
        if not cleaned:
            return []
        # True API accepts list of CIS in body for /cises/info (versions vary).
        data = self._request("POST", "/cises/info", body=cleaned, auth=True)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            rows = data.get("result") or data.get("cises") or data.get("data")
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        return []


def build_lk_receipt_document(
    *,
    inn: str,
    action: str = "DISTANCE",
    document_number: str,
    document_date: str,
    primary_document_type: str = "RECEIPT",
    products: list[dict[str, Any]],
    kpp: str = "",
    fias_id: str = "",
) -> dict[str, Any]:
    """Build product_document JSON for withdrawal (LK_RECEIPT)."""
    doc: dict[str, Any] = {
        "inn": str(inn or "").strip(),
        "action": str(action or "DISTANCE").strip() or "DISTANCE",
        "action_date": str(document_date or "").strip(),
        "document_type": str(primary_document_type or "RECEIPT").strip() or "RECEIPT",
        "document_number": str(document_number or "").strip(),
        "document_date": str(document_date or "").strip(),
        "products": products,
    }
    if kpp:
        doc["kpp"] = str(kpp).strip()
    if fias_id:
        doc["fias_id"] = str(fias_id).strip()
    return doc


def build_lp_return_document(
    *,
    inn: str,
    return_type: str = "REMOTE_SALE_RETURN",
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build product_document JSON for return to circulation (LP_RETURN)."""
    return {
        "inn": str(inn or "").strip(),
        "return_type": str(return_type or "REMOTE_SALE_RETURN").strip(),
        "products": products,
    }
