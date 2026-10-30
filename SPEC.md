# Pikanaut: specification for the typed-table iteration

This document consolidates the accepted design and records implementation choices
for previously unspecified details. The user authorized implementation after the
design discussion; JOIN is explicitly deferred. API examples below describe the
target of this iteration, not compatibility with the old decorator API.

## 1. Boundaries

Pikanaut builds parameterized SQL; it never opens connections, executes statements,
fetches existing rows, manages transactions or mutates models from returned rows.
The caller validates result mappings with any Pydantic model's model_validate().
Support SQLite 3.35+, the existing SQLite 3.34 surface, PostgreSQL numbered
placeholders and PostgreSQL psycopg placeholders. Keep Python >=3.10 support.
JOIN, aliases/self-JOIN, subqueries, upsert and migration generation are deferred.
Each query has one table source; other-table references must be rejected, not
silently added to FROM. Preserve raw(LiteralString) as an explicit escape hatch.

## 2. Table models

Use Pydantic TableModel with class keywords:

    class User(TableModel, table="users", schema="public"):
        id: int = IntColumn(pk=True)
        name: str = StrColumn(min_length=1, max_length=100)

No @table decorator or Skip. Every ordinary model field is a stored column;
ClassVar, PrivateAttr and computed_field are not stored columns. Metadata and
query methods must not occupy ordinary table-object column names. A subclass
without its own table is a reusable non-table base. Table/schema metadata is not
implicitly inherited. Table names are explicit; reject empty names, duplicate SQL
columns, unresolved/generic annotations, unsupported/mismatched column types and
contradictory constraints with SchemaError. A schema without table is invalid.

Defaults: extra="ignore", validate_assignment=True, validate_default=True, normal
Pydantic coercion. Standard Python value types are preserved. Users may configure
Pydantic normally, but bypassed validation/in-place container mutations are their
responsibility. INSERT does not repeat complete model validation.

Column declarations: IntColumn, FloatColumn, DecimalColumn, BoolColumn, StrColumn,
BytesColumn, UuidColumn, DateColumn, TimeColumn, DateTimeColumn, JsonColumn.
Declarations are optional if no configuration is needed. Common parameters: SQL
name, pk, unique, index, default/default_factory/server_default. Numeric bounds
use greater_than, greater_than_or_equal, less_than, less_than_or_equal. Strings use
min_length/max_length; regex, multiple_of, Decimal precision/scale are deferred.
Never silently accept an unsupported option. Bare int/str/etc. infer the matching
column. Homogeneous string/integer Literal and Enum store values, not names;
reject bool/float/mixed allowed-value sets. None controls SQL nullability.
Primary keys may not include None; missing generated keys use Generated instead.

## 3. Defaults and server-generated values

Exactly one of default, default_factory, server_default may be supplied.
A supported constant default supplies both model and DDL DEFAULT. Validate defaults
at model construction; never execute a factory to build DDL or generated code.
Python default_factory follows Pydantic construction semantics and emits no SQL
DEFAULT; its result is an ordinary bound INSERT value.

Generated is an explicit public marker type with singleton GENERATED. A server
field's annotation must include Generated; other fields must not. Omission fills
GENERATED only for server-generated fields. Generated is removed for SQL type and
column type inference; None is retained. Marker -> omit INSERT column; None -> SQL
NULL; actual value -> bound value, except ALWAYS identity rejects explicit values.
Serialization of an included GENERATED value fails explicitly, both model_dump
and model_dump_json; an explicitly excluded marker field may be omitted normally.
No automatic mutation/hydration of the input model after execution.

Library SQL descriptors belong exclusively to server_default. Portable NOW uses
PostgreSQL CURRENT_TIMESTAMP and SQLite
(strftime('%Y-%m-%dT%H:%M:%fZ', 'now')). Portable TODAY may use CURRENT_DATE.
Native descriptor namespaces preserve documented native behavior and reject use
with another dialect. Do not promise identical clock precision/transaction
semantics. UUID generation may use Python uuid4; any server UUID descriptor must
reject SQLite rather than emulate it. Identity(generated="BY_DEFAULT"|"ALWAYS")
defaults to BY_DEFAULT; requires an integer column. SQLite BY_DEFAULT identity
requires a single integer primary key; SQLite ALWAYS raises unsupported-feature.
NOW requires an aware datetime field; reject incompatible default/column pairs.

## 4. Values and constraints

Datetime defaults to aware values normalized to UTC; reject naive input.
DateTimeColumn(timezone=False) requires naive values and rejects aware input.
TimeColumn accepts naive time only. Persist SQLite date/time/UUID values in
consistent text formats that ordinary Pydantic can read.

JsonColumn supports nested Pydantic models and typed JSON structures; use
Pydantic JSON serialization, never default=str. Parse JSON text before validating
JsonColumn input; this behavior does not extend magically to arbitrary external
result models. Top-level None is SQL NULL, nested None is JSON null. Standalone
JSON-null documents are not a separate supported state. PostgreSQL stores JSONB;
SQLite stores valid JSON text. Enforce JSON validity in database DDL. Unknown
objects must fail rather than stringify silently.

DDL uses native constrained types when semantically appropriate (e.g. PostgreSQL
VARCHAR(max_length)), CHECK for remaining bounds/length/allowed-values, and no
redundant equivalent CHECK. SQLite Decimal is TEXT for exact storage. SQLite
Decimal numeric comparisons/IN, arithmetic, ordering, grouping, numeric aggregates
and numeric-bound CHECK are unsupported: raise UnsupportedOperation at build/DDL
rather than text ordering or REAL casts. Storage, reads, NULL tests and COUNT
remain supported. PostgreSQL supports Decimal operations and bounds. No rounding.

## 5. Typed tables and expressions

Generated .py files expose concrete attributes with meaningful value types, not
Any; reject misspelled attributes and incompatible expression/literal operands in
mypy and pyright. Carry table-source typing through expressions/conditions so
single-table queries cannot accidentally use another table. Runtime source and
capability validation remains necessary for dynamically supplied/untyped values.
Do not claim an unverified type-system guarantee; exercise positive and negative
contracts with both checkers, including nullable and foreign-source expressions.

Queries are constructed on db, not tables. Target calls:

    db.select(users)
    db.select(users.id, users.name)
    db.insert(users, User(...))
    db.insert_many(users, [User(...), User(...)])
    db.update(users).set(name="Alice").where(users.id == 1)
    db.delete(users).where(users.id == 1)

No required dynamic bind/columns step. Generated table objects are dialect
independent. All fluent builders are immutable; branches must be independent.
Keep existing aggregate/filter/limit/order/group/returning capabilities and safe
parameter binding. Dialect capabilities are checked at build; retain statically
restricted surfaces where compatible with the generated builders.

## 6. UPDATE

Generate a per-table total=False TypedDict and typed set(**Unpack[...]) signature.
It accepts field-appropriate literals or compatible same-source SQL expressions,
never GENERATED. Exclude ALWAYS identity columns from SET. Ordinary PK fields
remain writable; uniqueness/FK/cascades are database responsibilities.

Successive SET calls merge; the last assignment to the same field wins. Runtime
validation occurs at build and only on final assignments. Validate literals using
field types/constraints and autonomous field validators, not whole-model validators
or sibling field state. Sibling-dependent validators are unsupported for partial
UPDATE; never silently skip a validator or fake full-row state. SQL expressions
are not evaluated or passed through Python validators; check type/source/dialect,
and let database constraints validate computed results. No SET DEFAULT operation
in this iteration. UPDATE/DELETE require WHERE unless update_all/delete_all is
explicitly used. Repeated WHERE conditions combine with AND.

## 7. INSERT and batching

Include all model field values, including constants and factory results, except
GENERATED. Do not filter by model_fields_set. Reject mismatched models/tables and
illegal generated values without rerunning full model validation.

Ordinary build returns Sql, never a list. PostgreSQL mixed generated row shapes
use per-cell DEFAULT in one statement. SQLite mixed shapes raise an actionable
error recommending batch(). Empty-column rows must build valid DEFAULT VALUES
statements; if one statement cannot represent multiple empty rows, require batch.

batch() yields a distinct builder whose build returns list[Sql]. Preserve input
order, splitting contiguous shape-runs as SQLite requires and splitting further
by parameter-count/UTF-8 SQL-size limits. Do not globally regroup rows. If one row
cannot fit alone, raise QueryTooLong. Ordinary build raises rather than silently
batching. Propagate RETURNING to each statement where supported, without promising
returned-row positional correspondence; callers correlate stable keys themselves.

## 8. Generation CLI

Explicit workflow: pikanaut generate; normal application startup is independent.
No task-runner integration, automatic startup generation, watch mode, schema
fingerprints or runtime generated-code freshness checks. generate --check is
read-only and nonzero on missing/stale output. No implicit migration creation.

Application configuration (chosen concrete key names):

    [tool.pikanaut]
    models = ["app.models.users", "app.models.orders"]
    output_package = "app.generated"

Resolve from the application pyproject directory. Import only listed modules,
without recursive project scanning. Discover concrete TableModel classes declared
or re-exported there, deduplicating identical class objects; importing modules
executes application code. Root package resolution supports flat and src layouts;
provide an explicit output directory option if needed rather than guessing
ambiguous package roots. Tables without schema export from app.generated; schema
public exports from app.generated.public. Object names match SQL table names.
Reject invalid Python identifiers/keywords, duplicates and package/export
collisions without auto-renaming. Generated files import source models. Models
must not import their generated tables. Use a recognizable generated-file header;
never overwrite/delete unrelated user files. Deterministic output and cleanup of
stale owned files are covered by tests.

## 9. Compatibility and verification

This is a breaking API iteration: migrate repository tests/examples/docs to
TableModel and generated tables, rather than silently retaining Skip/@table as a
second model API. Keep independent Pydantic result models. Retain existing driver
placeholder, quoting, limit and real PostgreSQL coverage. Test new behavior before
implementing it, run pytest, strict mypy/pyright (including generated negative
contracts), build/install a wheel and exercise examples/CLI end to end. Report
actual checks and any remaining limitations, not merely expected behavior.

## 10. Known implementation gap

`users.id == "wrong"` and `users.id != "wrong"` are not rejected by mypy or
pyright. This is a limitation of both checkers, not a decision to weaken section
5; the equality operand typing that *can* be enforced is enforced:

- `Column` against a `Column` of another value type, of another nullable form, or
  from another table source is rejected by both checkers (`operator` /
  `reportOperatorIssue`), because each side's `__eq__` rejects the other operand.
- Scalar literals are accepted: for `==`/`!=` mypy (`checkexpr.py`,
  `check_op(..., allow_reverse=True)`) and pyright both fall back to the reflected
  operator, and builtin scalars declare `__eq__(self, value: object)`, so the
  reverse check always succeeds. mypy additionally suppresses its
  `--strict-equality` overlap diagnostic when either side defines a custom
  `__eq__` (`dangerous_comparison`: "We suppress the error for equality ...
  if there is a custom `__eq__()` method on either side"), which the SQL
  comparison API necessarily does.
- A negative contract `users.id == "wrong"  # type: ignore[operator]` therefore
  fails mypy with `Unused "type: ignore" comment` (`warn_unused_ignores`), and
  pyright reports nothing at all; the contract cannot be made green.
- Narrowing `__eq__` to overloads whose `object` fallback returns a marker type
  moves the failure to `.where(...)` only, requires suppressing
  `overload-overlap`/`reportInconsistentOverload`, and mistypes a value that is
  really `Cond`; it also rejects currently valid literal comparisons such as
  `Decimal` column against `int`. It was rejected as a fake guarantee.

Closing this exactly needs a type-checker hook: a mypy plugin (opt-in per
consumer project, so not portable) and an equivalent upstream change in pyright,
which has no plugin surface. Until then the gap stays documented here instead of
being claimed as enforced. Tests cover incompatible SET/IN values, arithmetic
operands, column-versus-column equality operands and query sources with both
checkers. The full Python 3.10–3.15 tox matrix runs green (`uv run tox`).

Reproduce with `tests/typing` on the path (mode `--strict`):

    users.id == "wrong"     # type: ignore[operator]  -> mypy: unused-ignore
    users.id == users.email # type: ignore[operator]  -> clean, error is reported
