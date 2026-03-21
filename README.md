# AI-reviews

Модуль для автоматической обработки отзывов.

## Что делает

`review_processor` автоматически обрабатывает отзывы и добавляет:

- нормализованный текст;
- оценку тональности (`positive` / `neutral` / `negative`);
- детекцию спама;
- детекцию токсичности;
- приоритет обработки (`low` / `medium` / `high`);
- рекомендуемое действие для команды поддержки.

## Структура

- `review_processor/models.py` — входная и выходная модели.
- `review_processor/processor.py` — правила анализа.
- `review_processor/cli.py` — пакетная обработка JSON.
- `tests/test_processor.py` — unit-тесты.

## Запуск CLI

Подготовьте JSON-массив отзывов, например `reviews.json`:

```json
[
  {
    "id": "r-1001",
    "text": "Отлично, удобно и быстро!",
    "author": "Alex",
    "rating": 5
  },
  {
    "id": "r-1002",
    "text": "Ужасно, приложение вылетает и не работает",
    "author": "Ivan",
    "rating": 1
  }
]
```

Обработайте файл:

```bash
python3 -m review_processor.cli --input reviews.json --output processed_reviews.json
```

## Запуск тестов

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```