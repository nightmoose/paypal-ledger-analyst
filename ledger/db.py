import decimal, os, shutil, time
import duckdb
from . import sqlguard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "ledger.duckdb")
MAX_ROWS = 200
_con = None

SCHEMA_DOC = """Tables (DuckDB, PayPal sandbox data, amounts in USD):
orders(id, status ['COMPLETED' captured | 'CREATED' not paid], create_time TIMESTAMP, amount, currency, description [product category], customer)
captures(id, order_id -> orders.id, status, create_time TIMESTAMP, amount, currency)
refunds(id, capture_id -> captures.id, status, create_time TIMESTAMP, amount [may be partial], currency)
invoices(id [e.g. INV2-...], number, status ['SENT' unpaid | 'MARKED_AS_PAID' | 'PAID' | ...], invoice_date DATE, due_date DATE, amount, paid_amount, currency, recipient_email)
An invoice is overdue when status not in ('PAID','MARKED_AS_PAID','CANCELLED') and due_date < current_date."""


def con():
    global _con
    if _con is None:
        path = SRC
        if not os.access(os.path.dirname(SRC), os.W_OK):  # serverless bundle is read-only
            path = "/tmp/ledger.duckdb"; shutil.copy(SRC, path)
        _con = duckdb.connect(path, read_only=True)
        _con.execute("SET enable_external_access=false")
        _con.execute("SET lock_configuration=true")
    return _con


def run(sql: str):
    s = sqlguard.check(sql)
    t = time.perf_counter()
    cur = con().cursor()
    cur.execute(f"SELECT * FROM ({s}) AS q LIMIT {MAX_ROWS}")
    cols = [d[0] for d in cur.description]
    rows = [[float(v) if isinstance(v, decimal.Decimal) else v if isinstance(v, (int, float, str, type(None))) else str(v)
             for v in r] for r in cur.fetchall()]
    return {"sql": s, "columns": cols, "rows": rows, "ms": round((time.perf_counter() - t) * 1000)}
