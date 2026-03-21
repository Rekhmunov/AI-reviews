# AI-reviews

Сервис обработки отзывов маркетплейсов (MVP в духе Spix): ленднинг, email/password авторизация, кабинет пользователя с левым меню, админ-панель, автоподтягивание отзывов по API, категоризация, шаблоны и ручная обработка оператором.

## Что реализовано сейчас

### 1) Лендинг + auth

- главная страница `/` как лендинг с преимуществами;
- кнопки входа и регистрации;
- регистрация/авторизация по email + password (без телефона/кодов);
- выход из аккаунта.

### 2) Админ-панель

URL: `/admin` (доступ только для роли `admin`)

- просмотр пользователей;
- смена ролей (`user` / `admin`);
- настройка AI-классификатора:
  - `rules` (встроенные правила),
  - `yandex` (Foundation Models API; API key/folder/model URI).

Текущая модель доступа:

- первый зарегистрированный пользователь становится `admin`;
- дальше админ может назначать роль другим пользователям.

### 3) Кабинет сервиса (`/app`)

Интерфейс: слева навигация, справа рабочее поле.

Разделы:

- **Отзывы**: синхронизация, фильтры, автоответ, перевод в ручную очередь, ручной ответ;
- **Кабинеты API**: подключение нескольких кабинетов WB/OZON (и `mock`);
- **Шаблоны**: процесс по категориям (`auto` / `manual` / `ignore`) и текст шаблонов.

### 4) Логика процессов

После синхронизации отзыв:

1. анализируется (`sentiment/spam/toxicity/priority`);
2. получает категорию:
   - `negative_delivery`
   - `negative_product`
   - `negative_other`
   - `positive_quality`
   - `positive_product`
   - `neutral_other`
3. для категории применяется правило:
   - `auto` -> автоответ по шаблону;
   - `manual` -> очередь оператора;
   - `ignore` -> игнор.

## Структура

- `review_processor/web.py` — FastAPI: лендинг, auth, app, admin, API.
- `review_processor/repository.py` — SQLite: users/sessions/accounts/templates/reviews/AI settings.
- `review_processor/service.py` — синхронизация, категоризация, процессы и ответы.
- `review_processor/processor.py` — rule-based анализ отзывов.
- `review_processor/auth.py` — hash/verify password и токены сессий.
- `tests/test_*.py` — unit-тесты.

## Быстрый старт

1. Установка зависимостей:

```bash
python3 -m pip install -r requirements.txt
```

2. Запуск:

```bash
python3 -m uvicorn review_processor.web:app --host 0.0.0.0 --port 8000
```

3. Открыть:

```text
http://localhost:8000
```

## Основные API endpoints

- `GET /api/me`
- `POST /api/sync` (`all_accounts=true` или `account_id`)
- `GET /api/reviews?priority=&status=&category=`
- `POST /api/reviews/{review_uid}/auto-reply`
- `POST /api/reviews/{review_uid}/queue-manual`
- `POST /api/reviews/{review_uid}/manual-reply`
- `GET/POST /api/accounts`, `POST /api/accounts/{id}/status`
- `GET/PUT /api/templates`
- `GET/PUT /api/admin/ai-settings` (admin)
- `GET /api/admin/users`, `POST /api/admin/users/{id}/role` (admin)

## Подключение Яндекс ИИ

Поддержка уже заложена:

1. зайдите в `/admin`;
2. выберите provider = `yandex`;
3. укажите `yandex_api_key`, `yandex_folder_id` (и опционально `yandex_model_uri`);
4. сохраните настройки.

Если настройки не заполнены или API недоступен, система автоматически fallback'ится на встроенную rule-based категоризацию.

## CLI (базовая пакетная обработка JSON)

```bash
python3 -m review_processor.cli --input reviews.json --output processed_reviews.json
```

## Тесты

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```