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
- SLA-метрики и мониторинг ручной очереди.
- журнал действий (синхронизация, автоответы, ручные действия операторов).

Текущая модель доступа:

- первый зарегистрированный пользователь становится `admin`;
- дальше админ может назначать роль другим пользователям.

### 3) Кабинет сервиса (`/app`)

Интерфейс: слева навигация, справа рабочее поле.

Разделы:

- **Отзывы**: синхронизация, фильтры, автоответ, перевод в ручную очередь, ручной ответ;
- **Вопросы и чаты**: вопросы маркетплейсов и переписки с покупателями (статусы open/waiting/closed);
- **Аналитика**: ключевые метрики (обработано, доля позитива/негатива, вопросы/чаты);
- **Настройки**: источники API + правила обработки/шаблоны.

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

### 5) Интеграции WB/OZON

- поддержаны отдельные клиенты для WB и OZON с пагинацией;
- для OZON используется `client_id + api_key`;
- для WB используется `api_key`;
- можно подключать несколько кабинетов каждого маркетплейса.
- добавлена нормализация ошибок API и retry для сетевых сбоев.

Дополнительные настройки интеграции можно передать через `integration` (JSON) при создании кабинета:

- для OZON:
  - `list_path` (по умолчанию `/v1/review/list`)
  - `page_size`, `max_pages`
  - `base_payload` (словарь, добавляется в каждую POST-загрузку)
- для WB:
  - `list_path` (если нужен явный path поверх base URL)
  - `page_size`, `max_pages`
  - `skip_param`, `take_param`, `unanswered_param`, `unanswered_value`

Пример payload для `POST /api/accounts` (OZON):

```json
{
  "marketplace": "ozon",
  "account_name": "Ozon Main",
  "api_url": "https://api-seller.ozon.ru",
  "api_key": "secret",
  "client_id": "12345",
  "integration": {
    "list_path": "/v1/review/list",
    "page_size": 50,
    "max_pages": 15,
    "base_payload": {
      "sort_dir": "DESC"
    }
  }
}
```

### 6) Безопасность API-ключей

- ключи API хранятся в БД только в зашифрованном виде;
- в интерфейсе отображается только маска ключа;
- для production обязательно задайте переменную окружения:

```bash
export APP_ENCRYPTION_KEY="<fernet-key>"
```

Если ключ не задан, используется dev fallback (подходит только для локальной разработки).

## Структура

- `review_processor/web.py` — FastAPI: лендинг, auth, app, admin, API.
- `review_processor/repository.py` — SQLite: users/sessions/accounts/templates/reviews/AI settings.
- `review_processor/service.py` — синхронизация, категоризация, процессы, ответы, WB/OZON клиенты.
- `review_processor/processor.py` — rule-based анализ отзывов.
- `review_processor/auth.py` — hash/verify password и токены сессий.
- `review_processor/security.py` — шифрование/дешифрование секретов.
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
  - в ответе для `all_accounts=true` возвращаются `success_accounts`, `failed_accounts`, `errors`
- `GET /api/reviews?priority=&status=&category=`
- `POST /api/reviews/{review_uid}/auto-reply`
- `POST /api/reviews/{review_uid}/queue-manual`
- `POST /api/reviews/{review_uid}/manual-reply`
- `GET /api/conversations?kind=&status=`
- `POST /api/conversations/{conversation_uid}/status`
- `GET /api/analytics`
- `GET/POST /api/accounts`, `POST /api/accounts/{id}/status`
- `GET/PUT /api/templates`
- `GET/PUT /api/admin/ai-settings` (admin)
- `GET /api/admin/users`, `POST /api/admin/users/{id}/role` (admin)
- `GET /api/admin/metrics` (admin)
- `GET /api/admin/actions` (admin)

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