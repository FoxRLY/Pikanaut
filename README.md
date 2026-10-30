# pikanaut

Параметризованный SQL и типизированные таблицы из Pydantic-моделей. Границы и
решения этой breaking-итерации описаны в [SPEC.md](SPEC.md). Примеры ниже и
исполняемые файлы в `examples/` проверены тестами на SQLite и PostgreSQL.

## Установка

```bash
uv add 'pikanaut @ git+https://github.com/FoxRLY/Pikanaut'
```

## Табличные модели и типизированные таблицы

Таблица — это `TableModel` с обязательным keyword `table` и необязательным
`schema`. Обычные поля модели являются сохраняемыми колонками; `ClassVar`,
`PrivateAttr` и `computed_field` колонками не становятся.

```python
from pikanaut import IntColumn, StrColumn, TableModel

class User(TableModel, table="users"):
    id: int = IntColumn(pk=True)
    email: str = StrColumn(max_length=320, unique=True)
    age: int | None = None
```

Доступны специализированные декларации `IntColumn`, `FloatColumn`,
`DecimalColumn`, `BoolColumn`, `StrColumn`, `BytesColumn`, `UuidColumn`,
`DateColumn`, `TimeColumn`, `DateTimeColumn` и `JsonColumn`. Они объединяют
метаданные колонки, ограничения Pydantic и DDL; если настройки не нужны,
подходит обычная аннотация (`name: str`). Числовые границы называются
`greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal`, а
для строк используются `min_length` и `max_length`.

Сгенерированный Python-модуль содержит конкретные типизированные атрибуты
таблиц. Например, для таблицы без схемы приложение использует:

```python
from app.generated import users

query = db.select(users.id, users.email).where(users.age >= 18).build()
```

Таблицы со схемой экспортируются из соответствующего пакета, например
`app.generated.public`. Модели не импортируют сгенерированные таблицы.

## Конфигурация и генерация

В `pyproject.toml` приложения укажите явные модули моделей и пакет вывода:

```toml
[tool.pikanaut]
models = ["app.models.users", "app.models.orders"]
output_package = "app.generated"
```

Генерация импортирует только перечисленные модули (импорт выполняет их код):

```bash
pikanaut generate
pikanaut generate --check  # read-only проверка отсутствующего/устаревшего вывода
```

Запуск приложения не запускает генерацию автоматически: нет hooks, watch-mode
или runtime fingerprints. Генерация таблиц также не создаёт миграции.

## Запросы

```python
from pikanaut import client
from pikanaut.dialects import SQLITE

db = client(SQLITE)
insert = db.insert(users, User(id=1, email="a@b.io", age=30)).build()
select = (
    db.select(users.id, users.email)
    .where((users.age >= 18) & (users.age < 65))
    .order_by(users.id.desc())
    .build()
)
update = db.update(users).set(email="new@b.io").where(users.id == 1).build()
delete = db.delete(users).where(users.id == 1).build()
```

Все значения передаются через параметры, а не вставляются в SQL. Builders
immutable: `where`, `set`, `limit`, `returning` и другие fluent-методы создают
новую ветку, не изменяя исходную. У generated table objects `set(...)` typed по
полям конкретной таблицы: принимаются только значения или совместимые
выражения соответствующего типа; `Generated` не является SET-значением.
`UPDATE` и `DELETE` требуют `WHERE`, если не выбран явный
`update_all()`/`delete_all()`.

Сгенерированный SQL исполняет вызывающая сторона. Например, после создания
схемы через DDL она может передать `statement.sql` и `statement.params` в
`sqlite3.Connection.execute`; pikanaut сам не открывает соединения, не
исполняет SQL и не управляет транзакциями.

Результат валидируется обычным Pydantic-маршрутом, без обязательного
табличного декодера:

```python
row = conn.execute(select.sql, select.params).fetchone()
result = UserResult.model_validate(dict(row))
```

## Значения по умолчанию и INSERT

`default`, `default_factory` и `server_default` взаимоисключающие.
Константный `default` валидируется Pydantic и задаёт SQL `DEFAULT`.
Обычный Python `default_factory` выполняется при создании модели; его результат
становится параметром INSERT и не превращается в SQL default и не выполняется
при генерации DDL.

`server_default` означает генерацию на стороне БД. Для такого поля аннотация
содержит `Generated`: `Generated` означает «опустить колонку, чтобы БД
применила default», а `None` означает SQL `NULL`; конкретное значение
передаётся параметром (кроме ограничений identity `ALWAYS`). `Generated` не
участвует в SQL-типе, а сериализация включённого неразрешённого marker-а
завершается явной ошибкой. Первичный ключ не может быть nullable: используйте
обычный тип с Python-фабрикой либо `T | Generated` с identity/server default.

INSERT включает значения, полученные из констант и Python-фабрик, кроме
`Generated`; заполненное значение не исчезает только потому, что поле не было
передано явно при создании модели.

## Диалекты, Decimal и batch

Поддерживаются `SQLITE`, `SQLITE_34`, `POSTGRES` и `POSTGRES_PSYCOPG`; диалект
определяет placeholders и доступные возможности. SQLite хранит `Decimal` как
TEXT: хранение, чтение, `NULL`-проверки и `COUNT` поддерживаются, но числовые
сравнения (включая `IN`), арифметика, сортировка, группировка, числовые
агрегаты и numeric-bound CHECK запрещены и должны завершаться
`UnsupportedOperation`, а не неявным сравнением текста или приведением к REAL.

Обычный `insert_many(...).build()` возвращает один `Sql`; смешанные формы строк
с `Generated` на SQLite требуют явного `.batch()`, чей `build()` возвращает
`list[Sql]`. Batch сохраняет порядок, разбивает последовательные совместимые
формы и учитывает лимиты параметров и UTF-8-размер SQL. PostgreSQL может
использовать `DEFAULT` по ячейкам в одном statement. Возвращённые строки не
обещают позиционное соответствие входным; при необходимости связывайте их по
стабильному ключу.

JOIN, upsert, подзапросы и миграции отложены. `raw()` остаётся явным escape hatch
для статических `LiteralString`-фрагментов.

## Разработка

```bash
uv sync
uv run pytest
uv run mypy
uv run pyright
uv run python examples/01_insert_select.py
```

Файлы примеров находятся в [`examples/README.md`](examples/README.md).
