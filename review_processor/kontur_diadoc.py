"""Клиент Diadoc API для Заявки (ЭЗЗ, LogisticsOrderRequest).

Контур.Логистика для эТрН принимает XML через logist-api; для Заявки
публично задокументирована отправка через Diadoc ``PostMessage``
(TypeNamedId=LogisticsOrderRequest).
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urljoin

_log = logging.getLogger(__name__)

DEFAULT_DIADOC_URL = "https://diadoc-api.kontur.ru/"


@dataclass
class DiadocResult:
    ok: bool
    status_code: int = 0
    data: dict[str, Any] | list[Any] | Any = None
    error: str = ""
    raw: str = ""
    token: str = ""


class KonturDiadocClient:
    def __init__(
        self,
        *,
        api_url: str = DEFAULT_DIADOC_URL,
        client_id: str,
        login: str = "",
        password: str = "",
        token: str = "",
        timeout: float = 60.0,
    ) -> None:
        url = (api_url or DEFAULT_DIADOC_URL).strip()
        if not url.endswith("/"):
            url += "/"
        self.api_url = url
        self.client_id = (client_id or "").strip()
        self.login = (login or "").strip()
        self.password = password or ""
        self.token = (token or "").strip()
        self.timeout = timeout

    def authenticate(self) -> DiadocResult:
        """V3 Authenticate (password) → access token."""
        if self.token:
            return DiadocResult(ok=True, status_code=200, token=self.token)
        if not self.client_id or not self.login or not self.password:
            return DiadocResult(ok=False, error="Не заданы Diadoc Client ID / логин / пароль")
        body = f"{self.login}\n{self.password}".encode("utf-8")
        headers = {
            "Authorization": f"DiadocAuth ddauth_api_client_id={self.client_id}",
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "text/plain",
            "User-Agent": "FeedPilot/1.0",
        }
        url = urljoin(self.api_url, "V3/Authenticate?type=password")
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                token = resp.read().decode("utf-8", errors="replace").strip()
                if not token:
                    return DiadocResult(ok=False, status_code=int(resp.status), error="Пустой токен Diadoc")
                self.token = token
                return DiadocResult(ok=True, status_code=int(resp.status), token=token)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return DiadocResult(ok=False, status_code=int(exc.code), error=raw[:500] or f"HTTP {exc.code}", raw=raw)
        except Exception as exc:
            return DiadocResult(ok=False, error=str(exc))

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            auth = self.authenticate()
            if not auth.ok:
                raise RuntimeError(auth.error or "Diadoc auth failed")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json; charset=utf-8",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "FeedPilot/1.0",
        }

    def _request(self, method: str, path: str, *, data: bytes | None = None) -> DiadocResult:
        try:
            headers = self._auth_headers()
        except RuntimeError as exc:
            return DiadocResult(ok=False, error=str(exc))
        url = urljoin(self.api_url, path.lstrip("/"))
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed: Any = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"raw": raw}
                return DiadocResult(ok=True, status_code=int(resp.status), data=parsed, raw=raw, token=self.token)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return DiadocResult(ok=False, status_code=int(exc.code), error=raw[:800] or f"HTTP {exc.code}", raw=raw)
        except Exception as exc:
            _log.exception("diadoc request failed: %s %s", method, path)
            return DiadocResult(ok=False, error=str(exc))

    def send_order_request(
        self,
        *,
        from_box_id: str,
        to_box_id: str,
        xml_bytes: bytes,
        signature_bytes: bytes,
        version: str = "zakzvper_05_01_01",
    ) -> DiadocResult:
        """PostMessage V3 — Т1 Заявки (LogisticsOrderRequest)."""
        payload = {
            "FromBoxId": from_box_id.strip(),
            "ToBoxId": to_box_id.strip(),
            "DocumentAttachments": [
                {
                    "SignedContent": {
                        "Content": base64.b64encode(xml_bytes).decode("ascii"),
                        "Signature": base64.b64encode(signature_bytes).decode("ascii"),
                    },
                    "TypeNamedId": "LogisticsOrderRequest",
                    "Function": "default",
                    "Version": version,
                }
            ],
        }
        return self._request("POST", "V3/PostMessage", data=json.dumps(payload).encode("utf-8"))

    def send_waybill_diadoc(
        self,
        *,
        from_box_id: str,
        to_box_id: str,
        xml_bytes: bytes,
        signature_bytes: bytes,
        version: str = "kl_trn_mt_05_01",
    ) -> DiadocResult:
        """Альтернативная отправка эТрН через Diadoc PostMessage."""
        payload = {
            "FromBoxId": from_box_id.strip(),
            "ToBoxId": to_box_id.strip(),
            "DocumentAttachments": [
                {
                    "SignedContent": {
                        "Content": base64.b64encode(xml_bytes).decode("ascii"),
                        "Signature": base64.b64encode(signature_bytes).decode("ascii"),
                    },
                    "TypeNamedId": "LogisticsWaybill",
                    "Function": "reception",
                    "Version": version,
                }
            ],
        }
        return self._request("POST", "V3/PostMessage", data=json.dumps(payload).encode("utf-8"))

    def get_document(self, *, box_id: str, message_id: str, entity_id: str) -> DiadocResult:
        qs = urlencode({"boxId": box_id, "messageId": message_id, "entityId": entity_id})
        return self._request("GET", f"V3/GetDocument?{qs}")

    @staticmethod
    def parse_post_message_ids(payload: Any) -> dict[str, str]:
        if not isinstance(payload, dict):
            return {}
        message_id = str(payload.get("MessageId") or payload.get("messageId") or "").strip()
        entity_id = ""
        entities = payload.get("Entities") or payload.get("entities") or []
        if isinstance(entities, list):
            for ent in entities:
                if not isinstance(ent, dict):
                    continue
                att = ent.get("Attachment") or ent.get("attachment") or {}
                named = str(
                    (att.get("AttachmentTypeNamedId") if isinstance(att, dict) else None)
                    or ent.get("AttachmentTypeNamedId")
                    or ""
                )
                if "Logistics" in named or ent.get("EntityType") in ("Attachment", "attachment", 1):
                    entity_id = str(ent.get("EntityId") or ent.get("entityId") or "").strip()
                    if entity_id:
                        break
            if not entity_id and entities:
                first = entities[0]
                if isinstance(first, dict):
                    entity_id = str(first.get("EntityId") or first.get("entityId") or "").strip()
        return {"message_id": message_id, "entity_id": entity_id}
