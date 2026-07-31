"""Translation between Databricks/Spark column types and DuckDB column types.

Unity Catalog speaks Spark's type vocabulary (`STRING`, `LONG`, `ARRAY<INT>`,
`STRUCT<a:INT>`); the tables underneath are really DuckDB (`VARCHAR`, `BIGINT`, `INT[]`,
`STRUCT(a INTEGER)`). This module is the only place that maps between them.

Two reasons it exists rather than splicing `type_text` straight into DDL:

1. The Spark spellings a Databricks user would naturally write — every complex type, plus
   `TIMESTAMP_NTZ` and `BYTE` — are parser errors in DuckDB.
2. `type_text` arrives from the API, so interpolating it into `CREATE TABLE` is a DDL
   injection point. Only strings this module generates reach DuckDB.

It also derives the rest of the SDK's `ColumnInfo` contract (`type_name`,
`type_precision`, `type_scale`, `type_json`) from the single `type_text` a caller
typically sends, so a create/get round trip through `databricks-sdk` comes back whole.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from minilake.errors import DatabricksError

# Scalar aliases → (DuckDB type, UC ColumnTypeName, Spark JSON type, canonical type_text).
# Both vocabularies are accepted on input: a Databricks user writes STRING, someone
# reading minilake's DuckDB underpinnings writes VARCHAR, and both must work.
#
# TIMESTAMP and TIMESTAMP_NTZ both land on DuckDB's naive TIMESTAMP. Spark distinguishes
# them (instant vs. local), but for a local emulator the surprise of TIMESTAMPTZ shifting
# literals costs more than the fidelity is worth.
_SCALARS: Dict[str, Tuple[str, str, str, str]] = {
    "STRING": ("VARCHAR", "STRING", "string", "string"),
    "VARCHAR": ("VARCHAR", "STRING", "string", "string"),
    "TEXT": ("VARCHAR", "STRING", "string", "string"),
    "CHAR": ("VARCHAR", "STRING", "string", "string"),
    "INT": ("INTEGER", "INT", "integer", "int"),
    "INTEGER": ("INTEGER", "INT", "integer", "int"),
    "LONG": ("BIGINT", "LONG", "long", "bigint"),
    "BIGINT": ("BIGINT", "LONG", "long", "bigint"),
    "SHORT": ("SMALLINT", "SHORT", "short", "smallint"),
    "SMALLINT": ("SMALLINT", "SHORT", "short", "smallint"),
    "BYTE": ("TINYINT", "BYTE", "byte", "tinyint"),
    "TINYINT": ("TINYINT", "BYTE", "byte", "tinyint"),
    "FLOAT": ("FLOAT", "FLOAT", "float", "float"),
    "REAL": ("FLOAT", "FLOAT", "float", "float"),
    "DOUBLE": ("DOUBLE", "DOUBLE", "double", "double"),
    "BOOLEAN": ("BOOLEAN", "BOOLEAN", "boolean", "boolean"),
    "BOOL": ("BOOLEAN", "BOOLEAN", "boolean", "boolean"),
    "DATE": ("DATE", "DATE", "date", "date"),
    "TIMESTAMP": ("TIMESTAMP", "TIMESTAMP", "timestamp", "timestamp"),
    "TIMESTAMP_NTZ": ("TIMESTAMP", "TIMESTAMP_NTZ", "timestamp_ntz", "timestamp_ntz"),
    "BINARY": ("BLOB", "BINARY", "binary", "binary"),
    "BLOB": ("BLOB", "BINARY", "binary", "binary"),
    "INTERVAL": ("INTERVAL", "INTERVAL", "interval", "interval"),
    "VARIANT": ("VARIANT", "VARIANT", "variant", "variant"),
    "NULL": ("VARCHAR", "NULL", "void", "void"),
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ColumnTypeSpec:
    """Everything the UC layer needs about one column type, derived from `type_text`."""

    duckdb_ddl: str
    type_name: str
    type_text: str
    type_precision: Optional[int] = None
    type_scale: Optional[int] = None
    spark_json: Any = "string"


@dataclass(frozen=True)
class _Parsed:
    duckdb: str
    type_name: str
    canonical: str
    spark_json: Any
    precision: Optional[int] = None
    scale: Optional[int] = None


def normalize_column_type(type_text: str, *, column: str = "") -> ColumnTypeSpec:
    """Parse a Databricks or DuckDB type name into everything UC needs.

    Raises DatabricksError(INVALID_REQUEST) on anything unrecognised, so the caller sees
    an actionable message instead of a raw DuckDB parser error surfacing three layers up.
    """
    parsed = _parse(type_text, column=column)
    return ColumnTypeSpec(
        duckdb_ddl=parsed.duckdb,
        type_name=parsed.type_name,
        type_text=parsed.canonical,
        type_precision=parsed.precision,
        type_scale=parsed.scale,
        spark_json=parsed.spark_json,
    )


def column_type_json(name: str, spec: ColumnTypeSpec, nullable: bool = True) -> str:
    """The SDK's `type_json`: the Spark StructField JSON for this column."""
    return json.dumps(
        {"name": name, "type": spec.spark_json, "nullable": nullable, "metadata": {}},
        separators=(",", ":"),
    )


def validate_identifier(name: str, kind: str) -> str:
    """Reject names that are not plain SQL identifiers.

    Catalog, schema, table and column names are interpolated into DDL, and the catalog
    name additionally becomes a filename (`catalogs/{name}.duckdb` in duckdb_pool). A
    name containing a quote or a path separator escapes both.
    """
    if not name or not _IDENTIFIER_RE.match(name):
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=(
                f"Invalid {kind} name '{name}': must start with a letter or underscore "
                "and contain only letters, digits and underscores"
            ),
            status_code=400,
        )
    return name


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse(text: str, *, column: str = "") -> _Parsed:
    raw = (text or "").strip()
    if not raw:
        raise _bad_type(text, column, "type is empty")

    # DuckDB array suffix: INT[], STRUCT(...)[]
    if raw.endswith("[]"):
        element = _parse(raw[:-2], column=column)
        return _array_of(element)

    head, args = _split_head_args(raw)
    upper = head.upper()

    if upper == "ARRAY":
        if len(args) != 1:
            raise _bad_type(text, column, "ARRAY takes exactly one element type")
        return _array_of(_parse(args[0], column=column))

    if upper == "MAP":
        if len(args) != 2:
            raise _bad_type(text, column, "MAP takes exactly two types: MAP<KEY,VALUE>")
        key, value = _parse(args[0], column=column), _parse(args[1], column=column)
        return _Parsed(
            duckdb=f"MAP({key.duckdb}, {value.duckdb})",
            type_name="MAP",
            canonical=f"map<{key.canonical},{value.canonical}>",
            spark_json={
                "type": "map",
                "keyType": key.spark_json,
                "valueType": value.spark_json,
                "valueContainsNull": True,
            },
        )

    if upper == "STRUCT":
        return _struct_of(args, text, column)

    if upper == "DECIMAL" or upper == "NUMERIC":
        precision, scale = _decimal_args(args, text, column)
        return _Parsed(
            duckdb=f"DECIMAL({precision},{scale})",
            type_name="DECIMAL",
            canonical=f"decimal({precision},{scale})",
            spark_json=f"decimal({precision},{scale})",
            precision=precision,
            scale=scale,
        )

    scalar = _SCALARS.get(upper)
    if scalar is None:
        raise _bad_type(text, column, f"unknown type '{head}'")

    duckdb, type_name, spark_json, canonical = scalar
    # CHAR(10) / VARCHAR(255): DuckDB ignores the length, Databricks keeps it in
    # type_text — and keeps the parameterized spelling, not the `string` alias.
    if args and upper in ("CHAR", "VARCHAR"):
        canonical = f"{upper.lower()}({args[0].strip()})"
    return _Parsed(duckdb=duckdb, type_name=type_name, canonical=canonical, spark_json=spark_json)


def _array_of(element: _Parsed) -> _Parsed:
    return _Parsed(
        duckdb=f"{element.duckdb}[]",
        type_name="ARRAY",
        canonical=f"array<{element.canonical}>",
        spark_json={
            "type": "array",
            "elementType": element.spark_json,
            "containsNull": True,
        },
    )


def _struct_of(args: List[str], text: str, column: str) -> _Parsed:
    if not args:
        raise _bad_type(text, column, "STRUCT needs at least one field")

    fields, ddl_parts, canon_parts = [], [], []
    for arg in args:
        name, _, field_text = arg.partition(":")
        # DuckDB's own spelling is `STRUCT(a INTEGER)` — space-separated, no colon.
        if not field_text:
            name, _, field_text = arg.strip().partition(" ")
        name, field_text = name.strip(), field_text.strip()
        if not name or not field_text:
            raise _bad_type(text, column, f"malformed STRUCT field '{arg.strip()}'")
        field = _parse(field_text, column=column)
        ddl_parts.append(f'"{name}" {field.duckdb}')
        canon_parts.append(f"{name}:{field.canonical}")
        fields.append({"name": name, "type": field.spark_json, "nullable": True, "metadata": {}})

    return _Parsed(
        duckdb=f"STRUCT({', '.join(ddl_parts)})",
        type_name="STRUCT",
        canonical=f"struct<{','.join(canon_parts)}>",
        spark_json={"type": "struct", "fields": fields},
    )


def _decimal_args(args: List[str], text: str, column: str) -> Tuple[int, int]:
    if not args:
        return 10, 0
    try:
        precision = int(args[0].strip())
        scale = int(args[1].strip()) if len(args) > 1 else 0
    except ValueError:
        raise _bad_type(text, column, "DECIMAL precision and scale must be integers")
    if len(args) > 2:
        raise _bad_type(text, column, "DECIMAL takes at most two arguments")
    return precision, scale


def _split_head_args(text: str) -> Tuple[str, List[str]]:
    """Split `STRUCT<a:INT,b:STRING>` or `DECIMAL(10,2)` into head and argument list."""
    for open_ch, close_ch in (("<", ">"), ("(", ")")):
        start = text.find(open_ch)
        if start == -1:
            continue
        if not text.rstrip().endswith(close_ch):
            break
        head = text[:start].strip()
        inner = text.rstrip()[start + 1 : -1]
        return head, _split_top_level(inner)
    return text.strip(), []


def _split_top_level(text: str) -> List[str]:
    """Split on commas that are not nested inside <> or ()."""
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in text:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _bad_type(text: str, column: str, reason: str) -> DatabricksError:
    where = f" for column '{column}'" if column else ""
    return DatabricksError(
        error_code="INVALID_REQUEST",
        message=(
            f"Unsupported column type '{text}'{where}: {reason}. "
            "Supported: STRING, INT, LONG, SHORT, BYTE, FLOAT, DOUBLE, BOOLEAN, DATE, "
            "TIMESTAMP, TIMESTAMP_NTZ, BINARY, INTERVAL, VARIANT, DECIMAL(p,s), "
            "ARRAY<T>, MAP<K,V>, STRUCT<a:T,...> (DuckDB spellings also accepted)"
        ),
        status_code=400,
    )
