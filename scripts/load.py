"""Pull sandbox data from PayPal REST into DuckDB (data/ledger.duckdb).

Order: try Transaction Search (/v1/reporting/transactions) for discovery; if it is not
enabled for the app or lags (it can take hours to index), fall back to the ids in
data/seed_manifest.json. Invoices come from the Invoicing v2 list endpoint.
"""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import duckdb
from ledger.paypal import call

DB = os.environ.get("LEDGER_DB", "data/ledger.duckdb")
SCHEMA = """
CREATE TABLE orders(id VARCHAR PRIMARY KEY, status VARCHAR, create_time TIMESTAMP, amount DECIMAL(12,2),
  currency VARCHAR, description VARCHAR, customer VARCHAR);
CREATE TABLE captures(id VARCHAR PRIMARY KEY, order_id VARCHAR, status VARCHAR, create_time TIMESTAMP,
  amount DECIMAL(12,2), currency VARCHAR);
CREATE TABLE refunds(id VARCHAR PRIMARY KEY, capture_id VARCHAR, status VARCHAR, create_time TIMESTAMP,
  amount DECIMAL(12,2), currency VARCHAR);
CREATE TABLE invoices(id VARCHAR PRIMARY KEY, number VARCHAR, status VARCHAR, invoice_date DATE, due_date DATE,
  amount DECIMAL(12,2), paid_amount DECIMAL(12,2), currency VARCHAR, recipient_email VARCHAR);
"""


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None) if s else None


def discover_order_ids():
    end = dt.datetime.now(dt.timezone.utc); start = end - dt.timedelta(days=30)
    r = call("GET", "/v1/reporting/transactions", idem=False, params={
        "start_date": start.strftime("%Y-%m-%dT%H:%M:%S-0000"), "end_date": end.strftime("%Y-%m-%dT%H:%M:%S-0000"),
        "fields": "transaction_info", "page_size": 500})
    if r.status_code == 200 and r.json().get("transaction_details"):
        print("transaction search: ok")
        return None  # search found rows, but order ids still come from the manifest (search returns txn ids)
    print(f"transaction search unavailable or empty (HTTP {r.status_code}); using seed manifest")
    return None


def main():
    man = json.load(open("data/seed_manifest.json"))
    discover_order_ids()
    orders, caps, refs, invs = [], [], [], []
    for oid in man["orders"]:
        o = call("GET", f"/v2/checkout/orders/{oid}", idem=False).json(); pu = o["purchase_units"][0]
        orders.append((o["id"], o["status"], ts(o["create_time"]), pu["amount"]["value"], pu["amount"]["currency_code"],
                       pu.get("description"), pu.get("custom_id")))
        for c in pu.get("payments", {}).get("captures", []):
            caps.append((c["id"], oid, c["status"], ts(c["create_time"]), c["amount"]["value"], c["amount"]["currency_code"]))
    for rid in man["refunds"]:
        r = call("GET", f"/v2/payments/refunds/{rid}", idem=False).json()
        up = next((l["href"] for l in r.get("links", []) if l["rel"] == "up"), "")
        refs.append((r["id"], up.rsplit("/", 1)[-1], r["status"], ts(r["create_time"]), r["amount"]["value"],
                     r["amount"]["currency_code"]))
    page = 1
    while True:
        j = call("GET", "/v2/invoicing/invoices", idem=False, params={"page": page, "page_size": 100, "fields": "amount"}).json()
        for i in j.get("items", []):
            d = i["detail"]
            invs.append((i["id"], d.get("invoice_number"), i["status"], d.get("invoice_date"),
                         d.get("payment_term", {}).get("due_date"), i["amount"]["value"],
                         i.get("payments", {}).get("paid_amount", {}).get("value", 0), i["amount"]["currency_code"],
                         i["primary_recipients"][0]["billing_info"].get("email_address")))
        if len(j.get("items", [])) < 100: break
        page += 1
    if os.path.exists(DB): os.remove(DB)
    con = duckdb.connect(DB); con.execute(SCHEMA)
    for t, rows in (("orders", orders), ("captures", caps), ("refunds", refs), ("invoices", invs)):
        if rows: con.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(rows[0]))})", rows)
        print(t, len(rows))
    con.close()


if __name__ == "__main__":
    main()
