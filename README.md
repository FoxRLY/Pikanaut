# pikanaut

Генератор SQL из типизированных моделей pydantic. Не ORM: библиотека превращает
модель и выражения над её колонками в `(sql, params)` и на этом заканчивает.

```python
sql, params, _ = db.select(U.id, U.email).where(U.age > 18).order_by(U.id.desc()).build()
# sql    == 'SELECT "id","user_email" FROM "users" WHERE "age">? ORDER BY "id" DESC'
# params == [18]
```

## Что внутри и чего нет

| pikanaut делает | pikanaut не делает |
| --- | --- |
| модель → SQL-текст и список параметров | исполнение запросов, пулы, транзакции |
| типизированные выражения над колонками | валидацию и приведение типов — это pydantic |
| плейсхолдеры и адаптацию значений под диалект | превращение строк в объекты |
| проверку возможностей диалекта на этапе типов | сессии, identity map, ленивую загрузку |
| лимиты на длину запроса и число параметров | JOIN, upsert, подзапросы |
| CREATE TABLE / INDEX / DROP из модели | миграции и диффы схемы |

Зависимости: `pypika` (рендер выражений и кавычки), `pydantic` (модели). Python >= 3.13.
Пакет пока не опубликован — работать с ним можно из этого репозитория через `uv run`.

## Быстрый старт

```python
from typing import Annotated
import sqlite3

from pydantic import BaseModel
from pikanaut import Col, Skip, client, columns, table
from pikanaut.dialects import SQLITE

@table("users")
class User(BaseModel):
    id:            Annotated[int, Col(pk=True)]
    email:         Annotated[str, Col("user_email", unique=True)]
    password_hash: Annotated[str, Skip]        # есть в модели, нет в таблице
    age:           int | None = None

db = client(SQLITE)        # Client[SQLite]
U = columns(User)          # Columns[User]

insert = db.insert(User(id=1, email="a@b.io", password_hash="x", age=30)).build()
select = db.select(U.id, U.email).where(U.age > 18).limit(10).build()

conn = sqlite3.connect("app.db")
conn.execute(insert.sql, insert.params)
rows = conn.execute(select.sql, select.params).fetchall()   # [(1, 'a@b.io')]
```

Полный цикл обратно в модель — на стороне пользователя, силами pydantic:

```python
from pydantic import TypeAdapter

names = [d[0] for d in cursor.description]
users = [TypeAdapter(User).validate_python(dict(zip(names, row))) for row in rows]
```

## Модель

-   `@table("users", schema="public")` — декоратор поверх `pydantic.BaseModel`,
    возвращает тот же класс. Схема поддерживается не всеми диалектами.
-   Колонками становятся все обычные поля; `Skip` исключает поле, `Col(...)`
    переопределяет имя, `pk`, `unique`, SQL-тип.
-   Схема проверяется на импорте: дубли колонок, `TypeVar` в аннотации
    (generic-модели запрещены), все поля `Skip`, неизвестные метки → `SchemaError`.
-   `Skip`-поле остаётся обязательным для pydantic: значение нужно передать при
    создании объекта, хотя в БД оно не уходит.

## Выражения

```python
U.age > 18                   # сравнения: == != < <= > >=
U.age.in_([1, 2, 3])         # IN (разворачивается в ?,?,? или = ANY($1))
U.age.is_null()              # IS NULL;  is_not_null() — IS NOT NULL
U.email.like("%@corp%")
U.email.contains("corp")     # LIKE %corp%
(U.age > 18) & (U.age < 65)  # AND;  (a) | (b) — OR;  ~a — NOT
and_(a, b), or_(a, b), not_(a)
U.id.desc(), U.id.asc()
count(U.id), sum(U.amount), avg(U.amount), min(), max(), coalesce(), lower(), upper()
raw("...")                   # escape hatch
```

Три ловушки, которые библиотека закрывает осознанно:

-   `U.age == None` на nullable-колонке даёт `IS NULL`, а на NOT NULL — `TypeError`
    с подсказкой `.is_null()`. Молча сравнивать с NULL нельзя: в SQL это никогда не true.
-   `bool(cond)` поднимает `TypeError`. `if U.age > 18:` выглядит правдоподобно,
    но у объекта условия нет осмысленной истинности.
-   Скобки вокруг `&` обязательны: `U.a > 1 & U.b < 2` Python разбирает как
    `U.a > (1 & U.b) < 2`. Используйте `and_()`/`or_()`, если не хотите думать о приоритете.

## Диалекты

Диалект — это тип, а не строковый флаг:

```python
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34

client(SQLITE).select(U.id).where(U.age.in_([1, 2])).build()
# SELECT "id" FROM "users" WHERE "age" IN (?,?)

client(POSTGRES).select(U.id).where(U.age.in_([1, 2])).build()
# SELECT "id" FROM "users" WHERE "age" = ANY($1)   params=[[1, 2]]   (asyncpg)

client(POSTGRES_PSYCOPG).select(U.id).where(U.age > 18).build()
# SELECT "id" FROM "users" WHERE "age">%s                              (psycopg3)
```

| Диалект | Плейсхолдер | Особенности |
| --- | --- | --- |
| `SQLITE` | `?` | RETURNING (3.35+), `LIMIT -1 OFFSET n`, bool→0/1, datetime→ISO |
| `SQLITE_34` | `?` | то же без RETURNING — метода `returning()` у запросов нет |
| `POSTGRES` | `$n` | схема, ILIKE, массивы (`= ANY`), типы отдаются драйверу как есть; для asyncpg |
| `POSTGRES_PSYCOPG` | `%s` | то же самое, но под DB-API драйверы (psycopg2/psycopg3), которые сами переводят `%s` → `$n` |

Несовместимость видна до запуска: `client(SQLITE_34).insert(row).returning(U.id)` —
ошибка линтера «SQLite34Insert has no attribute returning», а не отказ базы в рантайме.
Смена диалекта — одна строка (`client(SQLITE)` → `client(POSTGRES)`); всё, что перестало
быть совместимым, линтер покажет списком.


## Схема (DDL)

Схема выводится из той же модели — тем же способом, что и запросы: без соединения и без
параметров, только текст.

```python
from pikanaut import ddl

for statement in ddl.create(User, dialect=POSTGRES):
    print(statement.sql)
# CREATE TABLE IF NOT EXISTS "users" ("id" INTEGER GENERATED BY DEFAULT AS IDENTITY,
#   "user_email" TEXT NOT NULL, ..., CONSTRAINT "pk_users" PRIMARY KEY ("id"),
#   CONSTRAINT "uq_users_email" UNIQUE ("user_email"))
# CREATE INDEX IF NOT EXISTS "ix_users_tenant" ON "users" ("tenant")

ddl.drop(User, dialect=POSTGRES).sql     # DROP TABLE IF EXISTS "users"
```

Правила:

-   `pk` + nullable → `INTEGER PRIMARY KEY` (SQLite, rowid) или
    `GENERATED BY DEFAULT AS IDENTITY` (Postgres); `pk` + NOT NULL → обычный `PRIMARY KEY`.
-   `DEFAULT` — только из `Col(default=...)`, плюс маркер `ddl.NOW` → `CURRENT_TIMESTAMP`.
    Дефолты pydantic в схему не попадают, и наоборот: SQL-дефолт не делает поле
    необязательным в модели — значение всё равно надо передать.
-   `Decimal` на SQLite — `TEXT` (точность важнее сравнений); для денег с арифметикой
    держите целые минорные единицы.
-   Незнакомый тип (вложенная модель, произвольный класс) → `SchemaError` с подсказкой
    `Col(type="...")`, а не молчаливый `TEXT`.

Миграции — отдельная задача: `ddl.create()` отдаёт список statement'ов, и в Alembic это
выглядит так (без autogenerate, он требует SQLAlchemy `MetaData`):

```python
def upgrade() -> None:
    for statement in ddl.create(User, dialect=POSTGRES):
        op.execute(statement.sql)


def downgrade() -> None:
    op.execute(ddl.drop(User, dialect=POSTGRES).sql)
```

## Лимиты

Базы ограничивают число параметров и длину текста запроса. Узнавать об этом от драйвера
дорого: у MySQL при превышении просто закрывается соединение. Поэтому проверка — в `build()`:

```python
db.select(U.id).where(U.id.in_(range(10_001))).build()
# QueryTooLong: sqlite: 10001 placeholders, limit 10000 (pikanaut default; engine max 32766)

loose = client(SQLITE, limits=Limits(max_params=20_000))                    # поднять
free  = client(SQLITE, limits=Limits(max_sql_bytes=None, max_params=None))  # снять
```

Дефолты политические, с запасом относительно движка: 10 000 параметров и 1 МБ текста.
Параметры считаются на каждом значении (ошибка приходит раньше, чем построена строка),
длина — после рендера, в байтах UTF-8. `QueryTooLong` наследуется от `QueryError`
и несёт `length`, `limit`, `kind`.

## Типизация

Статически проверяется то, что зависит от диалекта: возвращаемые классы запросов,
отсутствие `returning` у `SQLITE_34`, несовместимость `Client[Postgres]` и `Client[SQLite]`.

Форма строки намеренно остаётся `Any`: `columns(User).age` не может быть статически
`Column[int]` без mypy-плагина или генерации стабов, а оба варианта отложены.
Если понадобится — это отдельный шаг, ядро менять не придётся.

## Примеры

```bash
uv run python examples/01_hello.py       # от простого к сложному, 9 файлов
uv run python examples/09_ddl.py         # схема из модели: sqlite и postgres рядом
```

`examples/` — девять запускаемых сценариев: от одного SELECT до DDL и слоя-репозитория.
Каждый файл печатает настоящий SQL и, где нужно исполнение, использует stdlib `sqlite3`.

## Тесты

Нужен только `uv` — он поставит Python 3.13 и зависимости:

```bash
uv sync                 # окружение + dev-группа (pytest, mypy, pyright, testcontainers, psycopg)
uv run pytest           # без Docker: 86 passed, 9 skipped (~2 с)
                        # с Docker:  95 passed (~6 с)
```

Из 95 тестов 10 относятся к Postgres: девять идут против контейнера, один проверяет
только генерацию. Без доступного Docker эти девять **скипаются**, поэтому на машине без
Docker набор остаётся зелёным. Если нужно, чтобы отсутствие базы было
падением (CI), включите строгий режим:

```bash
PIKANAUT_REQUIRE_POSTGRES=1 uv run pytest tests/test_postgres.py -v
```

Первый запуск тянет образ `postgres:17-alpine` (~80 МБ, один контейнер на всю сессию);
дальше старт занимает 2–3 секунды.

### Что где проверяется

| Файл | Тестов | О чём |
| --- | --- | --- |
| `tests/test_schema.py` | 11 | модель → колонки: `Col`, `Skip`, computed/private, nullable, `SchemaError` |
| `tests/test_expr.py` | 13 | семантика условий: `== None`, `bool(cond)`, hash, AND/OR/NOT, LIKE |
| `tests/test_binding.py` | 4 | значения в `params`, адаптация типов под диалект |
| `tests/test_limits.py` | 11 | `QueryTooLong` до выполнения: параметры и байты UTF-8 |
| `tests/test_golden.py` | 22 | точный текст SQL на каждый диалект |
| `tests/test_sqlite_execution.py` | 4 | сгенерированные запросы исполняются настоящим `sqlite3` |
| `tests/test_sqlite_roundtrip.py` | 3 | полный цикл insert → select → update → delete, инъекция |
| `tests/test_ddl.py` | 15 | `CREATE TABLE` / `INDEX` / `DROP`: golden-строки + исполнение в sqlite |
| `tests/test_typing.py` | 2 | `tests/typing/*` проверяются mypy и pyright (`--warn-unused-ignores`) |
| `tests/test_postgres.py` | 10 | реальный сервер в контейнере: `%s`, identity, `NUMERIC`, `JSONB`, схема |

Схема таблиц в тестах и примерах создаётся тем же `ddl.create(...)`, что и в библиотеке:
сломается генератор DDL — упадут и тесты запросов.

### Отдельные проверки

```bash
uv run pytest -k "ddl or limits"             # по ключевым словам
uv run pytest tests/test_golden.py -q        # один файл
uv run pytest tests/test_postgres.py -v      # только Postgres, с именами тестов

uv run mypy                                  # strict: src + examples
uv run pyright                               # strict: src + examples
uv run mypy --strict --warn-unused-ignores tests/typing   # типовой контракт
```

`mypy` и `pyright` входят в dev-группу; отдельная настройка не нужна.

### Если что-то не запускается

-   **`permission denied ... /var/run/docker.sock`** — пользователь не в группе `docker`:

    ```bash
    sudo usermod -aG docker "$USER"
    newgrp docker      # в текущей сессии; после перелогина не нужно
    ```

-   **Postgres-тесты скипнулись молча** — так и задумано без Docker. Запустите с
    `PIKANAUT_REQUIRE_POSTGRES=1`, чтобы увидеть явную ошибку.
-   **Первый прогон долгий** — тянется образ `postgres:17-alpine`; последующие запуски
    берут его из локального кеша.
-   **`uv run pytest` не находит `psycopg`** — значит окружение не синхронизировано
    после обновления `pyproject.toml`: `uv sync`.

`SPEC.md` — решения по дизайну, проверенные факты и открытые вопросы.

## Границы v1

Нет JOIN, upsert, подзапросов, ALTER/диффов схемы, гидрации строк и авточанкинга. Всё это сознательно
снаружи: библиотека генерирует SQL и не принимает решений за вызывающий код.
