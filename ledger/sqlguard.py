"""Read-only SQL guard. Defense in depth: this check + a read_only DuckDB connection
with external access disabled + a row cap."""
import re
import duckdb

FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|create|drop|alter|truncate|attach|detach|copy|export|import|"
                       r"pragma|install|load|call|set|reset|vacuum|checkpoint|grant|revoke|begin|commit|rollback|use)\b", re.I)
FORBIDDEN_FN = re.compile(r"\b(read_\w+|glob|sniff_csv|parquet_\w+|httpfs|getenv|query_table|query)\s*\(", re.I)


class UnsafeSQL(ValueError):
    pass


def _strip(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return sql.strip().rstrip(";").strip()


def check(sql: str) -> str:
    """Return a cleaned single SELECT statement or raise UnsafeSQL."""
    s = _strip(sql)
    if not s:
        raise UnsafeSQL("empty query")
    try:
        stmts = duckdb.extract_statements(s)
    except Exception as e:  # parse error
        raise UnsafeSQL(f"could not parse: {e}")
    if len(stmts) != 1:
        raise UnsafeSQL("exactly one statement allowed")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise UnsafeSQL("only SELECT queries are allowed")
    if not re.match(r"^\s*(select|with|from|\()", s, re.I):
        raise UnsafeSQL("query must start with SELECT or WITH")
    # string literals can't smuggle keywords into execution, so ignore them for the keyword scan
    no_str = re.sub(r"'(?:[^']|'')*'", "''", s)
    if m := FORBIDDEN.search(no_str):
        raise UnsafeSQL(f"keyword not allowed: {m.group(1).upper()}")
    if m := FORBIDDEN_FN.search(no_str):
        raise UnsafeSQL(f"function not allowed: {m.group(1)}")
    return s
