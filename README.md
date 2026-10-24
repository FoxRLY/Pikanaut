# pikanaut

Генерация SQL из pydantic моделей.

## Установка

```bash
uv add 'pikanaut @ git+https://github.com/FoxRLY/Pikanaut'
```

## Пример

```python
import sqlite3
from contextlib import closing
from typing import Annotated

from pydantic import BaseModel
from pikanaut import Col, Skip, client, columns, ddl, table
from pikanaut.dialects import SQLITE

@table("users")
class User(BaseModel):
    id: Annotated[int, Col(pk=True)]
    email: Annotated[str, Col("user_email", unique=True)]
    password_hash: Annotated[str, Skip]
    age: int | None = None

db = client(SQLITE)
U = columns(User)
insert = db.insert(User(id=1, email="a@b.io", password_hash="x", age=30)).build()
query = db.select(U.id, U.email).where(U.age > 18).limit(10).build()

print(query.sql)
# SELECT "id","user_email" FROM "users" WHERE "age">? LIMIT 10
print(query.params)  # [18]

with closing(sqlite3.connect(":memory:")) as conn:
    for statement in ddl.create(User, dialect=SQLITE):
        conn.execute(statement.sql)
    conn.execute(insert.sql, insert.params)
    print(conn.execute(query.sql, query.params).fetchall())  # [(1, 'a@b.io')]
```

`Col` задаёт SQL-имя, ограничения, индекс, тип и default. `Skip` исключает поле
из SQL, но не из валидации pydantic. Схема задаётся через `@table(..., schema="public")`.

## Запросы

Продолжение примера выше:

```python
db.select(U.id).where((U.age >= 18) & (U.age < 65)).order_by(U.id.desc()).build()
db.update(User).set(age=31).where(U.id == 1).build()
db.delete(User).where(U.id == 1).build()
db.insert_many([User(id=2, email="b@b.io", password_hash="x")]).build()
```

- Условия: `&`, `|`, `~`, `and_`, `or_`, `not_`; вокруг сравнений нужны скобки.
- Колонки: `in_`, `not_in`, `is_null`, `is_not_null`, `like`, `ilike`, `contains`.
- Агрегаты: `count`, `sum`, `avg`, `min`, `max`; функции: `coalesce`, `lower`, `upper`.
- SELECT: `group_by`, `having`, `limit`, `offset`. Есть `returning` для поддерживающих диалектов.
- UPDATE/DELETE без WHERE запрещены; намеренно без условия — `update_all` / `delete_all`.
- `== None` даёт `IS NULL` только для nullable-колонок; иначе — `TypeError`.
  `bool(cond)` тоже запрещён.

## Диалекты

Импортируются из `pikanaut.dialects`:

| Диалект | Параметры | Особенности |
| --- | --- | --- |
| `SQLITE` | `?` | SQLite 3.35+, RETURNING, datetime → ISO, bool → 0/1 |
| `SQLITE_34` | `?` | Без RETURNING |
| `POSTGRES` | `$1`, `$2` | asyncpg; ILIKE, схемы, `IN` через `= ANY($1)` |
| `POSTGRES_PSYCOPG` | `%s` | PostgreSQL для psycopg2/3 |

Диалект определяет тип клиента и доступные методы. mypy/pyright проверяют
диалектные ограничения; типы динамических колонок остаются `Any`.

## DDL и лимиты

```python
from pikanaut.dialects import POSTGRES, Limits

statements = ddl.create(User, dialect=POSTGRES)  # таблица + индексы
statement = ddl.drop(User, dialect=POSTGRES)
db = client(SQLITE, limits=Limits(max_params=20_000))
```

- Автоматический id: `Annotated[int | None, Col(pk=True)] = None`.
  Обязательный `int` с `pk=True` не включает identity в PostgreSQL.
- SQL-default: `Col(default=...)` или `Col(default=ddl.NOW)`.
  Он не заменяет default в модели pydantic.
- `Decimal` в SQLite хранится как TEXT. Неизвестный SQL-тип — `SchemaError`;
  доверенный статический тип задаётся через `Col(type="...")`.
- Лимиты по умолчанию: 10 000 параметров и 1 000 000 байт SQL (UTF-8).
  Превышение — `QueryTooLong` при `build()`, с полями `kind`, `length`, `limit`.
  `None` в соответствующем поле `Limits` отключает проверку.

JOIN, upsert, подзапросы и миграции не реализованы. `raw()` — выход за пределы API;
он принимает только `LiteralString` и предназначен для статических SQL-фрагментов.

## Разработка

```bash
uv sync
uv run pytest
uv run mypy
uv run pyright
uv run python examples/01_hello.py

uv python install 3.10 3.11 3.12 3.13 3.14
uv run tox                   # вся матрица
uv run tox -e py310           # одна версия
PIKANAUT_REQUIRE_POSTGRES=1 uv run tox
```

102 теста; без Docker — 93 passed, 9 skipped. Postgres проверяется через
`testcontainers` (`postgres:17-alpine`). `PIKANAUT_REQUIRE_POSTGRES=1` запрещает
пропуск при недоступном Docker.

Tox проверяет установку wheel, тесты, типизацию и девять примеров на Python 3.10–3.14.
`.python-version` задаёт 3.13 для разработки, mypy/pyright нацелены на 3.10.
Зависимости tox берутся из dev-группы, без привязки к `uv.lock`.

Примеры от простого к сложному — в `examples/`, решения по дизайну — в `SPEC.md`.
