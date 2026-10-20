# Примеры pikanaut

От простого к сложному. Каждый файл запускается сам и печатает настоящий SQL;
там, где нужно исполнение, используется stdlib `sqlite3` — так видно границу
«библиотека генерирует, драйвер исполняет».

```
uv run python examples/01_hello.py
```

| Файл | О чём |
| --- | --- |
| `01_hello.py` | минимум: модель, `columns()`, один SELECT и исполнение через `sqlite3` |
| `02_crud.py` | INSERT из `model_fields_set`, SELECT, UPDATE, DELETE, защита от пустого WHERE |
| `03_filters.py` | `== None` → `IS NULL`, `in_`, `like`/`contains`, `and_`/`or_`, приоритет `&` |
| `04_aggregates.py` | `count`/`sum`/`avg`, GROUP BY + HAVING, ORDER BY, LIMIT/OFFSET |
| `05_dialects.py` | один запрос на SQLite и Postgres: `?` против `$1`, `IN` против `= ANY`, схема |
| `06_limits.py` | лимиты параметров и длины: `QueryTooLong` на `build()`, подъём лимита, чанки |
| `07_pydantic_roundtrip.py` | полный цикл: модель → SQL → драйвер → `TypeAdapter` обратно в модель |
| `08_repository.py` | слой-репозиторий, дженерик по диалекту, вставка чанками |
| `09_ddl.py` | схема из модели: CREATE TABLE/INDEX/DROP на sqlite и postgres |

## Что стоит запомнить

-   `pikanaut` возвращает `Sql(sql, params, dialect)`. Никакого исполнения внутри.
-   Значения никогда не попадают в текст запроса — только в `params`.
-   `WHERE` без условий в UPDATE/DELETE — `QueryError`; для всех строк есть
    `delete_all()` / `update_all()`.
-   Диалект — это тип: `client(SQLITE_34)` даёт клиент без `returning`, и это
    ловится линтером на строке вызова.
-   Схема (DDL) выводится из модели: `ddl.create(Model, dialect=...)` → список statement'ов;
    миграции — вне библиотеки (рецепт `op.execute` в корневом README).
-   Лимиты (10 000 параметров / 1 МБ) политические: поднимаются
    `client(SQLITE, limits=Limits(max_params=...))` или снимаются `None`.

## Чего в v1 нет

JOIN, upsert, ALTER/диффы схемы, гидрация строк (это pydantic), повторение/ретраи и транзакции —
всё это сознательно снаружи. Подробности и обоснования — в `SPEC.md`.
