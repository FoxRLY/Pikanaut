# Примеры pikanaut

Примеры используют typed-table API из [SPEC.md](../SPEC.md). Они исполняемые и
проверяются в тестовом прогоне; SQL выполняет вызывающий код, для этого
используется stdlib `sqlite3`.

```bash
uv run python examples/01_insert_select.py
```

| Файл | О чём |
| --- | --- |
| `01_insert_select.py` | `TableModel`, сгенерированная таблица `users`, параметризованный SELECT и optional `sqlite3` caller |
| `02_crud.py` | INSERT, SELECT, immutable UPDATE/DELETE и защита от пустого WHERE |
| `03_filters.py` | nullable-фильтры, `IN`, `like`/`contains`, логические условия и приоритет `&` |
| `04_aggregates.py` | `count`/`sum`/`avg`, GROUP BY + HAVING, ORDER BY, LIMIT/OFFSET |
| `05_dialects.py` | SQLite и PostgreSQL placeholders и диалектные возможности |
| `06_limits.py` | лимиты параметров/UTF-8 SQL, `QueryTooLong`, `batch()` и порядок строк |
| `07_pydantic_roundtrip.py` | SQL → caller/driver → обычный Pydantic `model_validate()` |
| `08_repository.py` | внешний repository layer и передача параметров вызывающему драйверу |
| `09_ddl.py` | DDL из `TableModel`: CREATE TABLE/INDEX/DROP для SQLite и PostgreSQL |

## Что стоит запомнить

- `pikanaut` возвращает `Sql(sql, params, dialect)`; соединения, execution и
  транзакции находятся снаружи.
- Значения никогда не попадают в текст запроса — только в `params`.
- `db.select(users)`, `db.insert(users, model)`, `db.update(users)` и
  `db.delete(users)` строятся вокруг generated table object; query builders
  immutable.
- `UPDATE`/`DELETE` без условий запрещены, если явно не выбран
  `update_all()`/`delete_all()`.
- При обычном `build()` смешанные SQLite INSERT-формы не скрыто превращаются в
  несколько statements: используйте `.batch()`, который возвращает список и
  сохраняет входной порядок.
- Результаты принимает любой подходящий Pydantic result model через
  `model_validate()`, а не обязательная гидрация в `TableModel`.

## Чего в этой итерации нет

JOIN, upsert, подзапросы и миграции отложены. Повторение запросов, retry,
управление транзакциями и фактическое исполнение также остаются во внешнем
приложении. Подробности — в корневом [README.md](../README.md) и
[SPEC.md](../SPEC.md).
