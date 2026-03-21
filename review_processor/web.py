from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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


class SyncRequest(BaseModel):
    account_id: int | None = Field(default=None, description="Specific marketplace account ID")
    all_accounts: bool = Field(default=True, description="Sync all active accounts")


class ManualReplyRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=120)
    response_text: str = Field(min_length=2, max_length=2000)


class AccountCreateRequest(BaseModel):
    marketplace: str = Field(description="wb|ozon|mock")
    account_name: str = Field(min_length=2, max_length=120)
    api_url: str = Field(min_length=3, max_length=2000)
    api_key: str | None = Field(default=None, max_length=2000)
    client_id: str | None = Field(default=None, max_length=200)
    integration: dict[str, object] | None = None


class AccountStatusRequest(BaseModel):
    is_active: bool


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
        return HTMLResponse(LANDING_HTML)

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
        except MarketplaceSyncError as exc:
            raise HTTPException(status_code=502, detail=f"Sync failed: {exc}") from exc
        return {"accounts": 1, "loaded": loaded}

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
            api_url=payload.api_url.strip(),
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


LANDING_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Reviews Platform</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; color: #111827; background: #f8fafc; }
    .hero { padding: 60px 24px; background: linear-gradient(120deg, #0f172a, #1d4ed8); color: white; }
    .container { max-width: 980px; margin: 0 auto; }
    h1 { font-size: 42px; margin: 0 0 12px 0; }
    .lead { max-width: 760px; color: #dbeafe; line-height: 1.6; }
    .actions { margin-top: 24px; display: flex; gap: 10px; flex-wrap: wrap; }
    .btn { padding: 11px 18px; border-radius: 8px; text-decoration: none; font-weight: 700; }
    .btn-primary { background: #facc15; color: #111827; }
    .btn-secondary { border: 1px solid #93c5fd; color: #dbeafe; }
    .section { padding: 36px 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }
    .card { background: #fff; border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(15,23,42,0.08); }
    .small { color: #6b7280; }
  </style>
</head>
<body>
  <section class="hero">
    <div class="container">
      <h1>Сервис ответов на отзывы для маркетплейсов</h1>
      <p class="lead">AI Reviews Platform автоматически забирает отзывы из кабинетов WB/OZON, классифицирует их с помощью ИИ и отправляет в нужный процесс: автоответ по шаблону, ручная очередь оператора или игнор.</p>
      <div class="actions">
        <a class="btn btn-primary" href="/register">Создать аккаунт</a>
        <a class="btn btn-secondary" href="/login">Войти</a>
      </div>
    </div>
  </section>

  <section class="section">
    <div class="container">
      <h2>Преимущества</h2>
      <div class="grid">
        <div class="card">
          <h3>Мультикабинеты</h3>
          <p class="small">Подключайте несколько кабинетов WB и OZON в одном интерфейсе.</p>
        </div>
        <div class="card">
          <h3>AI-категоризация</h3>
          <p class="small">Категории типа negative_delivery, negative_product, positive_product и другие.</p>
        </div>
        <div class="card">
          <h3>Гибкие процессы</h3>
          <p class="small">Для каждой категории настраивается режим: auto / manual / ignore.</p>
        </div>
        <div class="card">
          <h3>Контроль операторов</h3>
          <p class="small">Негатив в ручную очередь и обработка через единую панель.</p>
        </div>
      </div>
    </div>
  </section>
</body>
</html>
"""


def build_login_html(error: str | None = None) -> str:
    error_html = f"<p style='color:#dc2626'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Вход</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f3f4f6; margin: 0; }}
    .box {{ max-width: 420px; margin: 60px auto; background: #fff; padding: 22px; border-radius: 12px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); }}
    input {{ width: 100%; padding: 10px; margin: 8px 0; border-radius: 7px; border: 1px solid #d1d5db; box-sizing: border-box; }}
    button {{ width: 100%; padding: 10px; border-radius: 7px; border: 0; background: #2563eb; color: white; font-weight: 700; cursor: pointer; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <div class="box">
    <h2>Вход в сервис</h2>
    {error_html}
    <form method="post" action="/login">
      <label>Email</label>
      <input name="email" type="email" required />
      <label>Пароль</label>
      <input name="password" type="password" required />
      <button type="submit">Войти</button>
    </form>
    <p>Нет аккаунта? <a href="/register">Регистрация</a></p>
  </div>
</body>
</html>
"""


def build_register_html(error: str | None = None) -> str:
    error_html = f"<p style='color:#dc2626'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Регистрация</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f3f4f6; margin: 0; }}
    .box {{ max-width: 440px; margin: 60px auto; background: #fff; padding: 22px; border-radius: 12px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); }}
    input {{ width: 100%; padding: 10px; margin: 8px 0; border-radius: 7px; border: 1px solid #d1d5db; box-sizing: border-box; }}
    button {{ width: 100%; padding: 10px; border-radius: 7px; border: 0; background: #2563eb; color: white; font-weight: 700; cursor: pointer; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <div class="box">
    <h2>Регистрация</h2>
    {error_html}
    <form method="post" action="/register">
      <label>Email</label>
      <input name="email" type="email" required />
      <label>Пароль</label>
      <input name="password" type="password" required />
      <label>Повторите пароль</label>
      <input name="password_repeat" type="password" required />
      <button type="submit">Создать аккаунт</button>
    </form>
    <p>Уже есть аккаунт? <a href="/login">Войти</a></p>
  </div>
</body>
</html>
"""


def build_app_html(user: dict[str, object]) -> str:
    safe_email = escape(str(user["email"]))
    safe_role = escape(str(user["role"]))
    admin_link = '<a class="navbtn" href="/admin">Админ-панель</a>' if user.get("role") == "admin" else ""
    template = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Рабочий кабинет</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f3f4f6; }
    .layout { display: grid; grid-template-columns: 260px 1fr; min-height: 100vh; }
    .sidebar { background: #0f172a; color: #e2e8f0; padding: 16px; }
    .brand { font-weight: 700; margin-bottom: 10px; }
    .meta { font-size: 12px; color: #94a3b8; margin-bottom: 14px; line-height: 1.5; }
    .navbtn { display: block; color: #e2e8f0; text-decoration: none; padding: 9px 10px; border-radius: 8px; margin-bottom: 8px; background: #1e293b; border: 1px solid #334155; }
    .main { padding: 18px; }
    .panel { background: #fff; padding: 14px; border-radius: 10px; box-shadow: 0 1px 4px rgba(15,23,42,0.08); margin-bottom: 12px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    input, select, textarea, button { border: 1px solid #d1d5db; border-radius: 7px; padding: 8px; font-size: 14px; }
    textarea { min-height: 90px; min-width: 320px; }
    button { background: #2563eb; color: #fff; border-color: #2563eb; cursor: pointer; }
    button.secondary { background: #fff; color: #2563eb; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid #eee; padding: 8px; vertical-align: top; }
    .pill { border-radius: 999px; padding: 3px 8px; font-size: 11px; display: inline-block; }
    .high { background: #fee2e2; color: #991b1b; }
    .medium { background: #fef3c7; color: #92400e; }
    .low { background: #dcfce7; color: #166534; }
    .hidden { display: none; }
    .small { color: #6b7280; font-size: 12px; }
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">AI Reviews Platform</div>
      <div class="meta">user: __SAFE_EMAIL__<br/>role: __SAFE_ROLE__</div>
      <a class="navbtn" href="#" onclick="showSection('reviews')">Отзывы</a>
      <a class="navbtn" href="#" onclick="showSection('accounts')">Кабинеты API</a>
      <a class="navbtn" href="#" onclick="showSection('templates')">Шаблоны</a>
      __ADMIN_LINK__
      <a class="navbtn" href="/logout">Выйти</a>
    </aside>

    <main class="main">
      <section id="section-reviews">
        <div class="panel">
          <h3>Синхронизация</h3>
          <div class="row">
            <button onclick="syncAll()">Синхронизировать все активные кабинеты</button>
            <span id="syncInfo" class="small"></span>
          </div>
        </div>
        <div class="panel">
          <h3>Фильтры</h3>
          <div class="row">
            <select id="priorityFilter">
              <option value="">priority: all</option>
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
            <select id="statusFilter">
              <option value="">status: all</option>
              <option value="queued_for_operator">queued_for_operator</option>
              <option value="answered_auto">answered_auto</option>
              <option value="answered_manual">answered_manual</option>
              <option value="ignored">ignored</option>
            </select>
            <select id="categoryFilter">
              <option value="">category: all</option>
              <option value="negative_delivery">negative_delivery</option>
              <option value="negative_product">negative_product</option>
              <option value="negative_other">negative_other</option>
              <option value="positive_quality">positive_quality</option>
              <option value="positive_product">positive_product</option>
              <option value="neutral_other">neutral_other</option>
            </select>
            <button class="secondary" onclick="loadReviews()">Обновить</button>
          </div>
        </div>
        <div class="panel">
          <h3>Отзывы</h3>
          <table>
            <thead>
              <tr>
                <th>Review UID</th><th>Источник</th><th>Категория</th><th>Текст</th><th>Тональность</th><th>Priority</th><th>Status</th><th>Действия</th>
              </tr>
            </thead>
            <tbody id="reviewsTbody"></tbody>
          </table>
        </div>
      </section>

      <section id="section-accounts" class="hidden">
        <div class="panel">
          <h3>Добавить кабинет маркетплейса</h3>
          <div class="row">
            <select id="accMarketplace">
              <option value="wb">WB</option>
              <option value="ozon">OZON</option>
              <option value="mock">MOCK</option>
            </select>
            <input id="accName" type="text" placeholder="Название кабинета" />
            <input id="accApiUrl" type="text" size="40" placeholder="https://.../reviews" />
            <input id="accClientId" type="text" size="22" placeholder="OZON Client ID (optional)" />
            <input id="accApiKey" type="text" size="35" placeholder="API key (optional)" />
            <textarea id="accIntegration" placeholder='Integration JSON (optional), e.g. {"page_size": 100, "max_pages": 10}' style="min-height:44px;min-width:360px"></textarea>
            <button onclick="createAccount()">Сохранить</button>
          </div>
          <div id="accountsInfo" class="small"></div>
        </div>
        <div class="panel">
          <h3>Подключенные кабинеты</h3>
          <table>
            <thead><tr><th>ID</th><th>Marketplace</th><th>Name</th><th>API URL</th><th>Client ID</th><th>API key</th><th>Active</th><th>Actions</th></tr></thead>
            <tbody id="accountsTbody"></tbody>
          </table>
        </div>
      </section>

      <section id="section-templates" class="hidden">
        <div class="panel">
          <h3>Шаблоны по категориям</h3>
          <p class="small">Режимы: auto (автоответ), manual (в очередь оператора), ignore (пропустить).</p>
          <div class="row">
            <select id="tplCategory">
              <option value="negative_delivery">negative_delivery</option>
              <option value="negative_product">negative_product</option>
              <option value="negative_other">negative_other</option>
              <option value="positive_quality">positive_quality</option>
              <option value="positive_product">positive_product</option>
              <option value="neutral_other">neutral_other</option>
            </select>
            <select id="tplMode">
              <option value="auto">auto</option>
              <option value="manual">manual</option>
              <option value="ignore">ignore</option>
            </select>
          </div>
          <div class="row">
            <textarea id="tplText" placeholder="Шаблон ответа. Переменные: {author}, {rating}, {category}, {sentiment}"></textarea>
          </div>
          <button onclick="saveTemplate()">Сохранить шаблон</button>
          <div id="templatesInfo" class="small"></div>
        </div>
        <div class="panel">
          <h3>Текущие шаблоны</h3>
          <table>
            <thead><tr><th>Category</th><th>Mode</th><th>Template</th></tr></thead>
            <tbody id="templatesTbody"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    function esc(value) {
      return String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    }

    function showSection(section) {
      const ids = ["reviews", "accounts", "templates"];
      for (const id of ids) {
        document.getElementById("section-" + id).classList.add("hidden");
      }
      document.getElementById("section-" + section).classList.remove("hidden");
    }

    async function syncAll() {
      const payload = { all_accounts: true, account_id: null };
      const res = await fetch("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById("syncInfo").textContent = "Ошибка: " + (data.detail || "sync failed");
        return;
      }
      const failed = data.failed_accounts || 0;
      let text = `Кабинетов: ${data.accounts}, отзывов: ${data.loaded}`;
      if (failed > 0) {
        text += `, ошибок: ${failed}`;
      }
      document.getElementById("syncInfo").textContent = text;
      await loadReviews();
    }

    async function loadReviews() {
      const priority = document.getElementById("priorityFilter").value;
      const status = document.getElementById("statusFilter").value;
      const category = document.getElementById("categoryFilter").value;
      const query = new URLSearchParams();
      if (priority) query.set("priority", priority);
      if (status) query.set("status", status);
      if (category) query.set("category", category);

      const res = await fetch("/api/reviews?" + query.toString());
      const data = await res.json();
      const tbody = document.getElementById("reviewsTbody");
      tbody.innerHTML = "";
      for (const review of data.items) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${esc(review.review_uid)}</td>
          <td>${esc(review.source)}</td>
          <td>${esc(review.category)}</td>
          <td>
            <div>${esc(review.text)}</div>
            <div class="small">author: ${esc(review.author || "-")} | rating: ${esc(review.rating ?? "-")}</div>
            <div class="small">reply auto: ${esc(review.auto_reply || "-")}</div>
            <div class="small">reply manual: ${esc(review.manual_reply || "-")}</div>
          </td>
          <td>${esc(review.sentiment_label)}</td>
          <td><span class="pill ${esc(review.priority)}">${esc(review.priority)}</span></td>
          <td>${esc(review.status)}</td>
          <td class="actions">
            <button onclick="autoReply('${esc(review.review_uid)}')">Автоответ</button>
            <button class="secondary" onclick="queueManual('${esc(review.review_uid)}')">В ручную</button>
            <button class="secondary" onclick="manualReply('${esc(review.review_uid)}')">Ответ оператора</button>
          </td>
        `;
        tbody.appendChild(tr);
      }
    }

    async function loadAccounts() {
      const res = await fetch("/api/accounts");
      const data = await res.json();
      const tbody = document.getElementById("accountsTbody");
      tbody.innerHTML = "";
      for (const account of data.items) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${esc(account.id)}</td>
          <td>${esc(account.marketplace)}</td>
          <td>${esc(account.account_name)}</td>
          <td>${esc(account.api_url)}</td>
          <td>${esc((account.extra || {}).client_id || "-")}</td>
          <td>${esc(account.api_key_preview || "-")}</td>
          <td>${esc(account.is_active ? "yes" : "no")}</td>
          <td>
            <button class="secondary" onclick="toggleAccount(${account.id}, ${account.is_active ? "false" : "true"})">
              ${account.is_active ? "Отключить" : "Включить"}
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      }
    }

    async function createAccount() {
      let integration = null;
      const integrationRaw = document.getElementById("accIntegration").value.trim();
      if (integrationRaw) {
        try {
          integration = JSON.parse(integrationRaw);
        } catch (_) {
          document.getElementById("accountsInfo").textContent = "Ошибка: Integration JSON некорректный";
          return;
        }
      }
      const payload = {
        marketplace: document.getElementById("accMarketplace").value,
        account_name: document.getElementById("accName").value.trim(),
        api_url: document.getElementById("accApiUrl").value.trim(),
        client_id: document.getElementById("accClientId").value.trim() || null,
        api_key: document.getElementById("accApiKey").value.trim() || null,
        integration: integration
      };
      const res = await fetch("/api/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById("accountsInfo").textContent = "Ошибка: " + (data.detail || "save failed");
        return;
      }
      document.getElementById("accountsInfo").textContent = "Кабинет добавлен.";
      await loadAccounts();
    }

    async function toggleAccount(accountId, active) {
      const payload = { is_active: active };
      await fetch(`/api/accounts/${accountId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      await loadAccounts();
    }

    async function loadTemplates() {
      const res = await fetch("/api/templates");
      const data = await res.json();
      const tbody = document.getElementById("templatesTbody");
      tbody.innerHTML = "";
      for (const tpl of data.items) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(tpl.category)}</td><td>${esc(tpl.mode)}</td><td>${esc(tpl.template_text)}</td>`;
        tbody.appendChild(tr);
      }
    }

    async function saveTemplate() {
      const payload = {
        category: document.getElementById("tplCategory").value,
        mode: document.getElementById("tplMode").value,
        template_text: document.getElementById("tplText").value
      };
      const res = await fetch("/api/templates", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById("templatesInfo").textContent = "Ошибка: " + (data.detail || "save failed");
        return;
      }
      document.getElementById("templatesInfo").textContent = "Шаблон сохранен.";
      await loadTemplates();
    }

    async function queueManual(reviewId) {
      await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/queue-manual`, { method: "POST" });
      await loadReviews();
    }

    async function autoReply(reviewId) {
      const res = await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/auto-reply`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Ошибка автоответа");
        return;
      }
      alert("Автоответ: " + data.reply);
      await loadReviews();
    }

    async function manualReply(reviewId) {
      const operator = prompt("Имя оператора:");
      if (!operator) return;
      const text = prompt("Текст ручного ответа:");
      if (!text) return;
      const payload = { operator_name: operator, response_text: text };
      const res = await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/manual-reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Ошибка ручного ответа");
        return;
      }
      await loadReviews();
    }

    loadAccounts();
    loadTemplates();
    loadReviews();
  </script>
</body>
</html>
"""
    return (
        template.replace("__SAFE_EMAIL__", safe_email)
        .replace("__SAFE_ROLE__", safe_role)
        .replace("__ADMIN_LINK__", admin_link)
    )


def build_admin_html(user: dict[str, object]) -> str:
    safe_email = escape(str(user["email"]))
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Admin panel</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f3f4f6; color: #111827; }}
    .wrap {{ max-width: 980px; margin: 24px auto; padding: 0 12px; }}
    .panel {{ background: white; padding: 16px; border-radius: 10px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
    .row {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    input, select, button {{ border: 1px solid #d1d5db; border-radius: 7px; padding: 8px; }}
    button {{ background: #2563eb; color: white; border-color: #2563eb; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #eee; text-align: left; padding: 8px; }}
    .small {{ color: #6b7280; font-size: 12px; }}
    a {{ color: #2563eb; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h2>Админ-панель</h2>
      <p class="small">Вы вошли как: {safe_email}</p>
      <p class="small">Текущая модель админ-доступа: первый зарегистрированный пользователь получает роль admin. Далее admin может назначать роли другим пользователям.</p>
      <p><a href="/app">Вернуться в рабочий кабинет</a></p>
    </div>

    <div class="panel">
      <h3>AI-классификатор отзывов</h3>
      <div class="row">
        <select id="provider">
          <option value="rules">rules (встроенные правила)</option>
          <option value="yandex">yandex (Foundation Models API)</option>
        </select>
        <input id="apiKey" type="text" size="30" placeholder="Yandex API key" />
        <input id="folderId" type="text" size="20" placeholder="Yandex folder id" />
        <input id="modelUri" type="text" size="30" placeholder="gpt://<folder>/yandexgpt-lite/latest" />
        <button onclick="saveAiSettings()">Сохранить</button>
      </div>
      <div id="aiInfo" class="small"></div>
      <p class="small">Оставьте API key пустым, чтобы не менять текущий ключ. Для очистки укажите пустую строку явно через API.</p>
    </div>

    <div class="panel">
      <h3>Пользователи и роли</h3>
      <table>
        <thead><tr><th>ID</th><th>Email</th><th>Role</th><th>Action</th></tr></thead>
        <tbody id="usersTbody"></tbody>
      </table>
    </div>

    <div class="panel">
      <h3>SLA и загрузка поддержки</h3>
      <div class="row">
        <div><strong id="mTotal">0</strong><div class="small">Всего отзывов</div></div>
        <div><strong id="mAvg">0</strong><div class="small">Среднее время ответа (мин)</div></div>
        <div><strong id="mOverdue">0</strong><div class="small">Просрочено в ручной очереди (>24ч)</div></div>
      </div>
      <div id="mStatuses" class="small"></div>
    </div>

    <div class="panel">
      <h3>Лента действий</h3>
      <table>
        <thead><tr><th>Время</th><th>Пользователь</th><th>Review UID</th><th>Действие</th><th>Детали</th></tr></thead>
        <tbody id="actionsTbody"></tbody>
      </table>
    </div>
  </div>

  <script>
    function esc(value) {{
      return String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    }}

    async function loadAiSettings() {{
      const res = await fetch("/api/admin/ai-settings");
      const data = await res.json();
      if (!res.ok) {{
        document.getElementById("aiInfo").textContent = data.detail || "Ошибка";
        return;
      }}
      document.getElementById("provider").value = data.provider || "rules";
      document.getElementById("apiKey").value = "";
      document.getElementById("folderId").value = data.yandex_folder_id || "";
      document.getElementById("modelUri").value = data.yandex_model_uri || "";
      document.getElementById("aiInfo").textContent = data.has_yandex_api_key
        ? ("Текущий API key: " + (data.yandex_api_key_preview || "***"))
        : "API key пока не задан";
    }}

    async function saveAiSettings() {{
      const payload = {{
        provider: document.getElementById("provider").value,
        yandex_api_key: document.getElementById("apiKey").value.trim() || null,
        yandex_folder_id: document.getElementById("folderId").value.trim() || null,
        yandex_model_uri: document.getElementById("modelUri").value.trim() || null
      }};
      const res = await fetch("/api/admin/ai-settings", {{
        method: "PUT",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload)
      }});
      const data = await res.json();
      if (!res.ok) {{
        document.getElementById("aiInfo").textContent = "Ошибка: " + (data.detail || "save failed");
        return;
      }}
      document.getElementById("aiInfo").textContent = "Настройки сохранены";
      await loadAiSettings();
    }}

    async function loadUsers() {{
      const res = await fetch("/api/admin/users");
      const data = await res.json();
      const tbody = document.getElementById("usersTbody");
      tbody.innerHTML = "";
      for (const user of data.items || []) {{
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${{esc(user.id)}}</td>
          <td>${{esc(user.email)}}</td>
          <td>${{esc(user.role)}}</td>
          <td>
            <button onclick="setRole(${{user.id}}, '${{user.role === "admin" ? "user" : "admin"}}')">
              Сделать ${{user.role === "admin" ? "user" : "admin"}}
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      }}
    }}

    async function setRole(userId, role) {{
      const res = await fetch(`/api/admin/users/${{userId}}/role`, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ role }})
      }});
      const data = await res.json();
      if (!res.ok) {{
        alert(data.detail || "Ошибка смены роли");
        return;
      }}
      await loadUsers();
    }}

    async function loadMetrics() {{
      const res = await fetch("/api/admin/metrics");
      const data = await res.json();
      if (!res.ok) {{
        return;
      }}
      document.getElementById("mTotal").textContent = String(data.total_reviews || 0);
      document.getElementById("mAvg").textContent = String(data.avg_first_response_minutes || 0);
      document.getElementById("mOverdue").textContent = String(data.overdue_manual_queue_24h || 0);
      const statuses = data.status_counts || {{}};
      const parts = Object.entries(statuses).map(([k, v]) => `${{k}}: ${{v}}`);
      document.getElementById("mStatuses").textContent = parts.join(" | ");
    }}

    async function loadActions() {{
      const res = await fetch("/api/admin/actions?limit=50");
      const data = await res.json();
      const tbody = document.getElementById("actionsTbody");
      tbody.innerHTML = "";
      for (const item of data.items || []) {{
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${{esc(item.created_at)}}</td>
          <td>${{esc(item.actor)}}</td>
          <td>${{esc(item.review_uid || "-")}}</td>
          <td>${{esc(item.action_type)}}</td>
          <td>${{esc(JSON.stringify(item.details || {{}}))}}</td>
        `;
        tbody.appendChild(tr);
      }}
    }}

    loadAiSettings();
    loadUsers();
    loadMetrics();
    loadActions();
  </script>
</body>
</html>
"""
