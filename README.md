# AI-reviews

Сервис для обработки отзывов маркетплейсов: автоподтягивание по API, автоответы и ручная обработка оператором (например, негативных отзывов), в формате простого web-приложения.

## Возможности

- загрузка отзывов из API маркетплейса;
- автоматическая классификация (тональность, спам, токсичность, приоритет);
- автоответ по шаблону;
- перевод отзывов в очередь оператора;
- ручной ответ оператора;
- web-дашборд для работы с отзывами.

## Структура

- `review_processor/processor.py` — rule-based анализ отзывов.
- `review_processor/repository.py` — SQLite-хранилище.
- `review_processor/service.py` — workflow синхронизации и ответов.
- `review_processor/web.py` — FastAPI backend + простая web-страница.
- `review_processor/cli.py` — пакетная обработка JSON.
- `tests/test_*.py` — unit-тесты.

## Быстрый старт (веб-сайт)

1. Установите зависимости:

```bash
python3 -m pip install -r requirements.txt
```

2. Запустите сервер:

```bash
uvicorn review_processor.web:app --host 0.0.0.0 --port 8000
```

3. Откройте в браузере:

```text
http://localhost:8000
```

На странице можно:

- подтянуть отзывы (кнопка "Подтянуть отзывы");
- фильтровать по `priority` и `status`;
- отправить автоответ;
- поставить отзыв в ручную очередь;
- сохранить ручной ответ оператора.

## API (основные endpoints)

- `POST /api/sync` — загрузка отзывов из источника.
  - для демо: `{ "source": "mock" }`
  - для реального API: `{ "source": "ozon", "api_url": "https://.../reviews" }`
- `GET /api/reviews` — список отзывов (`?priority=high&status=queued_for_operator`)
- `POST /api/reviews/{review_id}/auto-reply`
- `POST /api/reviews/{review_id}/queue-manual`
- `POST /api/reviews/{review_id}/manual-reply`

## CLI (пакетная обработка JSON)

```bash
python3 -m review_processor.cli --input reviews.json --output processed_reviews.json
```

## Запуск тестов

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```