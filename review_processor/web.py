from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .repository import ReviewRepository
from .service import HTTPMarketplaceClient, MockMarketplaceClient, ReviewAutomationService


class SyncRequest(BaseModel):
    source: str = Field(default="mock", description="Marketplace source identifier")
    api_url: str | None = Field(default=None, description="External marketplace API URL")


class ManualReplyRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=120)
    response_text: str = Field(min_length=2, max_length=2000)


def create_app(db_path: str = "reviews.db") -> FastAPI:
    repository = ReviewRepository(db_path=db_path)
    service = ReviewAutomationService(repository)

    app = FastAPI(title="Marketplace Reviews Assistant", version="1.0.0")

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/api/reviews")
    def list_reviews(priority: str | None = None, status: str | None = None) -> dict[str, object]:
        items = service.list_reviews(priority=priority, status=status)
        return {"items": items, "count": len(items)}

    @app.post("/api/sync")
    def sync_reviews(payload: SyncRequest) -> dict[str, object]:
        if payload.source == "mock":
            client = MockMarketplaceClient()
        else:
            if not payload.api_url:
                raise HTTPException(status_code=400, detail="api_url is required for non-mock source")
            client = HTTPMarketplaceClient(payload.api_url)

        loaded = service.sync_reviews(source=payload.source, client=client)
        return {"loaded": loaded}

    @app.post("/api/reviews/{review_id}/queue-manual")
    def queue_manual(review_id: str) -> dict[str, object]:
        updated = service.queue_for_manual_processing(review_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Review not found")
        return {"ok": True}

    @app.post("/api/reviews/{review_id}/auto-reply")
    def auto_reply(review_id: str) -> dict[str, object]:
        try:
            reply = service.generate_auto_reply(review_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "reply": reply}

    @app.post("/api/reviews/{review_id}/manual-reply")
    def manual_reply(review_id: str, payload: ManualReplyRequest) -> dict[str, object]:
        updated = service.save_manual_reply(
            review_id=review_id,
            operator_name=payload.operator_name,
            response_text=payload.response_text,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Review not found")
        return {"ok": True}

    return app


app = create_app()


DASHBOARD_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Marketplace Reviews Assistant</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f6f7fb; color: #222; }
    h1 { margin-bottom: 8px; }
    .panel { background: #fff; border-radius: 10px; padding: 16px; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
    .row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
    input, select, button, textarea { padding: 8px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; }
    button { cursor: pointer; background: #2563eb; border-color: #2563eb; color: #fff; }
    button.secondary { background: #fff; color: #2563eb; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; background: #fff; }
    th, td { border-bottom: 1px solid #eee; text-align: left; padding: 8px; vertical-align: top; }
    .pill { border-radius: 999px; padding: 3px 8px; font-size: 11px; display: inline-block; }
    .high { background: #fee2e2; color: #991b1b; }
    .medium { background: #fef3c7; color: #92400e; }
    .low { background: #dcfce7; color: #166534; }
    .status { font-weight: 600; }
    .small { color: #666; font-size: 12px; }
    .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  </style>
</head>
<body>
  <h1>Отзывы маркетплейсов</h1>
  <p class="small">Автозагрузка по API + ручная обработка оператором (негатив / high priority).</p>

  <div class="panel">
    <h3>Синхронизация</h3>
    <div class="row">
      <select id="source">
        <option value="mock">mock (демо)</option>
        <option value="wildberries">wildberries</option>
        <option value="ozon">ozon</option>
      </select>
      <input id="apiUrl" type="text" size="45" placeholder="https://marketplace.example/api/reviews" />
      <button onclick="syncReviews()">Подтянуть отзывы</button>
    </div>
    <div id="syncResult" class="small"></div>
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
        <option value="new">new</option>
        <option value="queued_for_operator">queued_for_operator</option>
        <option value="answered_auto">answered_auto</option>
        <option value="answered_manual">answered_manual</option>
      </select>
      <button class="secondary" onclick="loadReviews()">Обновить список</button>
    </div>
  </div>

  <div class="panel">
    <h3>Список отзывов</h3>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Источник</th><th>Текст</th><th>Тональность</th><th>Приоритет</th><th>Статус</th><th>Действия</th>
        </tr>
      </thead>
      <tbody id="reviewsTbody"></tbody>
    </table>
  </div>

  <script>
    function esc(value) {
      return String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    }

    async function syncReviews() {
      const source = document.getElementById("source").value;
      const apiUrl = document.getElementById("apiUrl").value.trim();
      const payload = { source: source, api_url: apiUrl || null };
      const res = await fetch("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById("syncResult").textContent = "Ошибка: " + (data.detail || "sync failed");
        return;
      }
      document.getElementById("syncResult").textContent = "Подтянуто отзывов: " + data.loaded;
      await loadReviews();
    }

    async function loadReviews() {
      const priority = document.getElementById("priorityFilter").value;
      const status = document.getElementById("statusFilter").value;
      const query = new URLSearchParams();
      if (priority) query.set("priority", priority);
      if (status) query.set("status", status);

      const res = await fetch("/api/reviews?" + query.toString());
      const data = await res.json();
      const tbody = document.getElementById("reviewsTbody");
      tbody.innerHTML = "";
      for (const review of data.items) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${esc(review.review_id)}</td>
          <td>${esc(review.source)}</td>
          <td>
            <div>${esc(review.text)}</div>
            <div class="small">author: ${esc(review.author || "-")} | rating: ${esc(review.rating ?? "-")}</div>
            <div class="small">reply auto: ${esc(review.auto_reply || "-")}</div>
            <div class="small">reply manual: ${esc(review.manual_reply || "-")}</div>
          </td>
          <td>${esc(review.sentiment_label)}</td>
          <td><span class="pill ${esc(review.priority)}">${esc(review.priority)}</span></td>
          <td class="status">${esc(review.status)}</td>
          <td class="actions">
            <button onclick="autoReply('${esc(review.review_id)}')">Автоответ</button>
            <button class="secondary" onclick="queueManual('${esc(review.review_id)}')">В ручную</button>
            <button class="secondary" onclick="manualReply('${esc(review.review_id)}')">Ответ оператора</button>
          </td>
        `;
        tbody.appendChild(tr);
      }
    }

    async function queueManual(reviewId) {
      await fetch(`/api/reviews/${reviewId}/queue-manual`, { method: "POST" });
      await loadReviews();
    }

    async function autoReply(reviewId) {
      const res = await fetch(`/api/reviews/${reviewId}/auto-reply`, { method: "POST" });
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
      const res = await fetch(`/api/reviews/${reviewId}/manual-reply`, {
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

    loadReviews();
  </script>
</body>
</html>
"""
