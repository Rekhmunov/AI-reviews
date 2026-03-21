from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import create_session_token, hash_password, verify_password
from .repository import ReviewRepository
from .service import MarketplaceSyncError, ReviewAutomationService

CATEGORIES = [
    "negative_delivery",
    "negative_product",
    "negative_other",
    "positive_quality",
    "positive_product",
    "neutral_other",
]

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "web_templates"
STATIC_DIR = BASE_DIR / "web_static"


class SyncRequest(BaseModel):
    account_id: int | None = Field(default=None, description="Specific marketplace account ID")
    all_accounts: bool = Field(default=True, description="Sync all active accounts")


class ManualReplyRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=120)
    response_text: str = Field(min_length=2, max_length=2000)


class AccountCreateRequest(BaseModel):
    marketplace: str = Field(description="wb|ozon|mock")
    account_name: str = Field(min_length=2, max_length=120)
    api_url: str | None = Field(default=None, max_length=2000)
    api_key: str | None = Field(default=None, max_length=2000)
    client_id: str | None = Field(default=None, max_length=200)
    integration: dict[str, object] | None = None


class AccountStatusRequest(BaseModel):
    is_active: bool


class ConversationStatusRequest(BaseModel):
    status: str = Field(description="open|waiting|closed")


class TemplateUpsertRequest(BaseModel):
    category: str
    mode: str = Field(description="auto|manual|ignore")
    template_text: str = Field(max_length=4000)


class AISettingsRequest(BaseModel):
    provider: str = Field(description="rules|yandex")
    yandex_api_key: str | None = None
    yandex_folder_id: str | None = None
    yandex_model_uri: str | None = None


class RoleUpdateRequest(BaseModel):
    role: str = Field(description="user|admin")


def create_app(db_path: str = "reviews.db") -> FastAPI:
    repository = ReviewRepository(db_path=db_path)
    service = ReviewAutomationService(repository)

    app = FastAPI(title="Marketplace Reviews Assistant", version="1.0.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    def _issue_session(user_id: int) -> str:
        token = create_session_token()
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        repository.create_session(token=token, user_id=user_id, expires_at=expires)
        return token

    def _get_current_user(request: Request) -> dict[str, object] | None:
        token = request.cookies.get("session_token")
        if not token:
            return None
        repository.cleanup_expired_sessions(_now_iso())
        return repository.get_session_user(token)

    def _require_user(request: Request) -> dict[str, object]:
        user = _get_current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Auth required")
        return user

    def _require_admin(request: Request) -> dict[str, object]:
        user = _require_user(request)
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access only")
        return user

    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request) -> HTMLResponse:
        user = _get_current_user(request)
        if user is not None:
            return RedirectResponse("/app", status_code=302)
        return HTMLResponse(build_landing_html())

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        user = _get_current_user(request)
        if user is not None:
            return RedirectResponse("/app", status_code=302)
        return HTMLResponse(build_login_html())

    @app.post("/login")
    def login(email: str = Form(...), password: str = Form(...)) -> HTMLResponse:
        user = repository.get_user_by_email(email)
        if user is None or not verify_password(password, str(user["password_hash"])):
            return HTMLResponse(build_login_html(error="Неверный email или пароль"), status_code=401)

        token = _issue_session(int(user["id"]))
        response = RedirectResponse("/app", status_code=302)
        response.set_cookie("session_token", token, httponly=True, samesite="lax")
        return response

    @app.get("/register", response_class=HTMLResponse)
    def register_page(request: Request) -> HTMLResponse:
        user = _get_current_user(request)
        if user is not None:
            return RedirectResponse("/app", status_code=302)
        return HTMLResponse(build_register_html())

    @app.post("/register")
    def register(email: str = Form(...), password: str = Form(...), password_repeat: str = Form(...)) -> HTMLResponse:
        email = email.strip().lower()
        if len(email) < 5 or "@" not in email:
            return HTMLResponse(build_register_html(error="Введите корректный email"), status_code=400)
        if len(password) < 8:
            return HTMLResponse(build_register_html(error="Пароль должен быть не короче 8 символов"), status_code=400)
        if password != password_repeat:
            return HTMLResponse(build_register_html(error="Пароли не совпадают"), status_code=400)
        if repository.get_user_by_email(email) is not None:
            return HTMLResponse(build_register_html(error="Пользователь уже существует"), status_code=409)

        role = "admin" if repository.count_users() == 0 else "user"
        user = repository.create_user(email=email, password_hash=hash_password(password), role=role)
        token = _issue_session(int(user["id"]))
        response = RedirectResponse("/app", status_code=302)
        response.set_cookie("session_token", token, httponly=True, samesite="lax")
        return response

    @app.get("/logout")
    def logout(request: Request) -> RedirectResponse:
        token = request.cookies.get("session_token")
        if token:
            repository.delete_session(token)
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie("session_token")
        return response

    @app.get("/app", response_class=HTMLResponse)
    def app_dashboard(request: Request) -> HTMLResponse:
        user = _get_current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=302)
        return HTMLResponse(build_app_html(user))

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page(request: Request) -> HTMLResponse:
        user = _get_current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=302)
        if user.get("role") != "admin":
            return HTMLResponse("<h1>Доступ запрещен</h1><p>Нужны права администратора.</p>", status_code=403)
        return HTMLResponse(build_admin_html(user))

    @app.get("/api/me")
    def get_me(request: Request) -> dict[str, object]:
        user = _require_user(request)
        return {"id": user["id"], "email": user["email"], "role": user["role"]}

    @app.get("/api/reviews")
    def list_reviews(
        request: Request,
        priority: str | None = None,
        status: str | None = None,
        category: str | None = None,
    ) -> dict[str, object]:
        user = _require_user(request)
        items = service.list_reviews(
            user_id=int(user["id"]),
            priority=priority,
            status=status,
            category=category,
        )
        return {"items": items, "count": len(items)}

    @app.get("/api/conversations")
    def list_conversations(
        request: Request,
        kind: str | None = None,
        status: str | None = None,
    ) -> dict[str, object]:
        user = _require_user(request)
        items = repository.list_conversations(
            user_id=int(user["id"]),
            kind=kind,
            status=status,
        )
        return {"items": items, "count": len(items)}

    @app.post("/api/conversations/{conversation_uid}/status")
    def set_conversation_status(
        conversation_uid: str,
        payload: ConversationStatusRequest,
        request: Request,
    ) -> dict[str, object]:
        user = _require_user(request)
        status_value = payload.status.strip().lower()
        if status_value not in {"open", "waiting", "closed"}:
            raise HTTPException(status_code=400, detail="status must be one of: open, waiting, closed")
        updated = repository.update_conversation_status(
            user_id=int(user["id"]),
            conversation_uid=conversation_uid,
            status=status_value,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Conversation not found")
        repository.log_review_action(
            user_id=int(user["id"]),
            review_uid=conversation_uid,
            action_type="conversation_status",
            actor=str(user["email"]),
            details={"status": status_value},
        )
        return {"ok": True}

    @app.get("/api/analytics")
    def user_analytics(request: Request) -> dict[str, object]:
        user = _require_user(request)
        return repository.get_user_analytics(user_id=int(user["id"]))

    @app.post("/api/sync")
    def sync_reviews(request: Request, payload: SyncRequest) -> dict[str, object]:
        user = _require_user(request)
        user_id = int(user["id"])
        if payload.all_accounts:
            return service.sync_all_accounts(user_id=user_id)

        if payload.account_id is None:
            raise HTTPException(status_code=400, detail="account_id is required if all_accounts=false")
        account = repository.get_marketplace_account(
            user_id=user_id,
            account_id=payload.account_id,
            include_secrets=True,
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Marketplace account not found")
        marketplace = str(account["marketplace"])
        try:
            client = service._build_client(account)
            loaded = service.sync_reviews(
                user_id=user_id,
                source=marketplace,
                account_id=int(account["id"]),
                client=client,
            )
            loaded_conversations = service.sync_conversations(
                user_id=user_id,
                source=marketplace,
                account_id=int(account["id"]),
                client=client,
            )
        except MarketplaceSyncError as exc:
            raise HTTPException(status_code=502, detail=f"Sync failed: {exc}") from exc
        return {"accounts": 1, "loaded": loaded, "loaded_conversations": loaded_conversations}

    @app.get("/api/accounts")
    def list_accounts(request: Request) -> dict[str, object]:
        user = _require_user(request)
        items = repository.list_marketplace_accounts(user_id=int(user["id"]))
        return {"items": items, "count": len(items)}

    @app.post("/api/accounts")
    def create_account(request: Request, payload: AccountCreateRequest) -> dict[str, object]:
        user = _require_user(request)
        marketplace = payload.marketplace.strip().lower()
        if marketplace not in {"wb", "ozon", "mock"}:
            raise HTTPException(status_code=400, detail="marketplace must be one of: wb, ozon, mock")
        integration = payload.integration if isinstance(payload.integration, dict) else {}
        default_api_urls = {
            "wb": "https://feedbacks-api.wildberries.ru/api/v1/feedbacks",
            "ozon": "https://api-seller.ozon.ru",
            "mock": "https://example.local/api/reviews",
        }
        api_url = (payload.api_url or "").strip() or str(integration.get("api_url") or default_api_urls[marketplace])
        if marketplace in {"wb", "ozon"} and not (payload.api_key or "").strip():
            raise HTTPException(status_code=400, detail="api_key is required for WB/OZON")
        client_id_value = (payload.client_id or "").strip() or str(integration.get("client_id") or "").strip()
        if marketplace == "ozon" and not client_id_value:
            raise HTTPException(status_code=400, detail="client_id is required for OZON")
        if client_id_value:
            integration["client_id"] = client_id_value
        if marketplace == "ozon":
            page_size = integration.get("page_size")
            if page_size is not None and (not isinstance(page_size, int) or page_size <= 0):
                raise HTTPException(status_code=400, detail="integration.page_size must be positive integer")
        if marketplace == "wb":
            max_pages = integration.get("max_pages")
            if max_pages is not None and (not isinstance(max_pages, int) or max_pages <= 0):
                raise HTTPException(status_code=400, detail="integration.max_pages must be positive integer")

        account = repository.create_marketplace_account(
            user_id=int(user["id"]),
            marketplace=marketplace,
            account_name=payload.account_name.strip(),
            api_url=api_url,
            api_key=(payload.api_key or "").strip() or None,
            extra=integration,
        )
        return {"ok": True, "item": account}

    @app.post("/api/accounts/{account_id}/status")
    def update_account_status(account_id: int, request: Request, payload: AccountStatusRequest) -> dict[str, object]:
        user = _require_user(request)
        updated = repository.update_marketplace_account_status(
            user_id=int(user["id"]),
            account_id=account_id,
            is_active=payload.is_active,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Marketplace account not found")
        return {"ok": True}

    @app.get("/api/templates")
    def list_templates(request: Request) -> dict[str, object]:
        user = _require_user(request)
        items = repository.list_templates(user_id=int(user["id"]))
        return {"items": items, "count": len(items)}

    @app.put("/api/templates")
    def upsert_template(request: Request, payload: TemplateUpsertRequest) -> dict[str, object]:
        user = _require_user(request)
        category = payload.category.strip().lower()
        mode = payload.mode.strip().lower()
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
        if mode not in {"auto", "manual", "ignore"}:
            raise HTTPException(status_code=400, detail="mode must be one of: auto, manual, ignore")
        repository.upsert_template(
            user_id=int(user["id"]),
            category=category,
            mode=mode,
            template_text=payload.template_text.strip(),
        )
        return {"ok": True}

    @app.post("/api/reviews/{review_id}/queue-manual")
    def queue_manual(review_id: str, request: Request) -> dict[str, object]:
        user = _require_user(request)
        updated = service.queue_for_manual_processing(user_id=int(user["id"]), review_uid=review_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Review not found")
        return {"ok": True}

    @app.post("/api/reviews/{review_id}/auto-reply")
    def auto_reply(review_id: str, request: Request) -> dict[str, object]:
        user = _require_user(request)
        try:
            reply = service.generate_auto_reply(user_id=int(user["id"]), review_uid=review_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "reply": reply}

    @app.post("/api/reviews/{review_id}/manual-reply")
    def manual_reply(review_id: str, payload: ManualReplyRequest, request: Request) -> dict[str, object]:
        user = _require_user(request)
        updated = service.save_manual_reply(
            user_id=int(user["id"]),
            review_uid=review_id,
            operator_name=payload.operator_name,
            response_text=payload.response_text,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Review not found")
        return {"ok": True}

    @app.get("/api/admin/ai-settings")
    def get_ai_settings(request: Request) -> dict[str, object]:
        _require_admin(request)
        return repository.get_ai_settings()

    @app.put("/api/admin/ai-settings")
    def update_ai_settings(request: Request, payload: AISettingsRequest) -> dict[str, object]:
        _require_admin(request)
        provider = payload.provider.strip().lower()
        if provider not in {"rules", "yandex"}:
            raise HTTPException(status_code=400, detail="provider must be one of: rules, yandex")
        repository.update_ai_settings(
            provider=provider,
            yandex_api_key=payload.yandex_api_key.strip() if payload.yandex_api_key is not None else None,
            yandex_folder_id=(payload.yandex_folder_id or "").strip() or None,
            yandex_model_uri=(payload.yandex_model_uri or "").strip() or None,
        )
        return {"ok": True}

    @app.get("/api/admin/users")
    def admin_list_users(request: Request) -> dict[str, object]:
        _require_admin(request)
        items = repository.list_users()
        return {"items": items, "count": len(items)}

    @app.post("/api/admin/users/{target_user_id}/role")
    def admin_update_user_role(target_user_id: int, payload: RoleUpdateRequest, request: Request) -> dict[str, object]:
        current_user = _require_admin(request)
        role = payload.role.strip().lower()
        if role not in {"user", "admin"}:
            raise HTTPException(status_code=400, detail="role must be user or admin")

        if role == "user":
            admin_rows = repository.raw_fetch("SELECT id FROM users WHERE role = 'admin'")
            if len(admin_rows) <= 1 and any(int(item["id"]) == target_user_id for item in admin_rows):
                raise HTTPException(status_code=400, detail="Нельзя снять роль последнего администратора")

        updated = repository.update_user_role(user_id=target_user_id, role=role)
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return {"ok": True, "by_admin": current_user["email"]}

    @app.get("/api/admin/metrics")
    def admin_metrics(request: Request) -> dict[str, object]:
        _require_admin(request)
        return repository.get_sla_metrics(user_id=None)

    @app.get("/api/admin/actions")
    def admin_actions(request: Request, limit: int = 100) -> dict[str, object]:
        _require_admin(request)
        rows = repository.list_recent_actions(user_id=None, limit=min(max(limit, 1), 500))
        return {"items": rows, "count": len(rows)}

    @app.exception_handler(HTTPException)
    def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app


app = create_app()

def _render_template(name: str, context: dict[str, str] | None = None) -> str:
    template_path = TEMPLATES_DIR / name
    html = template_path.read_text(encoding="utf-8")
    for key, value in (context or {}).items():
        html = html.replace(f"{{{{{key}}}}}", value)
    return html


def build_landing_html() -> str:
    return _render_template("landing.html")


def build_login_html(error: str | None = None) -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return _render_template("login.html", {"ERROR_HTML": error_html})


def build_register_html(error: str | None = None) -> str:
    error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
    return _render_template("register.html", {"ERROR_HTML": error_html})


def build_app_html(user: dict[str, object]) -> str:
    safe_email = escape(str(user["email"]))
    safe_role = escape(str(user["role"]))
    admin_link = '<a class="navbtn" href="/admin">Админ-панель</a>' if user.get("role") == "admin" else ""
    return _render_template(
        "app.html",
        {
            "SAFE_EMAIL": safe_email,
            "SAFE_ROLE": safe_role,
            "ADMIN_LINK": admin_link,
        },
    )


def build_admin_html(user: dict[str, object]) -> str:
    safe_email = escape(str(user["email"]))
    return _render_template("admin.html", {"SAFE_EMAIL": safe_email})
