"""Seed a PayPal *sandbox* merchant with orders, captures, refunds and invoices.

Usage: python scripts/seed.py   (needs PAYPAL_SANDBOX_CLIENT_ID / PAYPAL_SANDBOX_SECRET)
Writes data/seed_manifest.json with the created ids so the loader can fetch them
even when Transaction Search is unavailable or lagging.
"""
import json, os, random, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ledger.paypal import call

random.seed(7)
CUSTOMERS = ["Acme Outfitters", "Sample Bistro", "Northwind Books", "Blue Harbor Cafe", "Juniper Studio",
             "Maple & Co", "Riverbend Bikes", "Copperleaf Tea", "Summit Gear", "Lumen Labs"]
CATS = {"Coffee beans": (12, 45), "Gift card": (25, 100), "Workshop seat": (80, 250), "Subscription box": (30, 60),
        "Hardware kit": (120, 480)}
CARD = {"number": "4032039317984658", "expiry": "2030-12", "security_code": "123", "name": "Sandbox Buyer"}


def order(capture: bool):
    cat = random.choice(list(CATS)); lo, hi = CATS[cat]
    amt = f"{random.uniform(lo, hi):.2f}"; cust = random.choice(CUSTOMERS)
    body = {"intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": "USD", "value": amt},
            "description": cat, "custom_id": cust[:127]}]}
    if capture:
        body["payment_source"] = {"card": CARD}
    r = call("POST", "/v2/checkout/orders", json=body); r.raise_for_status(); return r.json()


def main():
    m = {"orders": [], "refunds": [], "invoices": []}
    for i in range(50):
        o = order(capture=i < 40); m["orders"].append(o["id"]); print("order", o["id"], o["status"])
    caps = []
    for oid in m["orders"][:40]:
        o = call("GET", f"/v2/checkout/orders/{oid}", idem=False).json()
        for c in o["purchase_units"][0].get("payments", {}).get("captures", []):
            caps.append((c["id"], c["amount"]["value"]))
    for cid, val in random.sample(caps, 8):
        partial = random.random() < 0.4
        body = {"amount": {"currency_code": "USD", "value": f"{float(val) / 2:.2f}"}} if partial else {}
        r = call("POST", f"/v2/payments/captures/{cid}/refund", json=body); r.raise_for_status()
        m["refunds"].append(r.json()["id"]); print("refund", r.json()["id"], "partial" if partial else "full")
    today = dt.date.today()
    emails = ["ap@acme-outfitters.example.com", "ops@sample-bistro.example.com", "billing@northwind.example.com",
              "owner@blueharbor.example.com", "studio@juniper.example.com"]
    for i in range(20):
        due = today + dt.timedelta(days=random.randint(-21, 15)); issued = due - dt.timedelta(days=14)
        amt = f"{random.choice([89.99, 150, 240, 480, 615.5, 1250, 1875]):.2f}"
        body = {"detail": {"currency_code": "USD", "invoice_date": issued.isoformat(),
                           "payment_term": {"due_date": due.isoformat()}, "note": "Thanks for your business!"},
                "invoicer": {"name": {"given_name": "Ledger", "surname": "Demo"}},
                "primary_recipients": [{"billing_info": {"email_address": emails[i % len(emails)]}}],
                "items": [{"name": random.choice(list(CATS)), "quantity": "1",
                           "unit_amount": {"currency_code": "USD", "value": amt}}]}
        r = call("POST", "/v2/invoicing/invoices", json=body); r.raise_for_status()
        inv_id = r.json().get("id") or r.json()["href"].rsplit("/", 1)[-1]
        s = call("POST", f"/v2/invoicing/invoices/{inv_id}/send", json={"send_to_invoicer": False})
        print("invoice", inv_id, due, "send", s.status_code)
        if i % 4 == 0:  # mark ~5 as paid
            p = call("POST", f"/v2/invoicing/invoices/{inv_id}/payments",
                     json={"method": "BANK_TRANSFER", "amount": {"currency_code": "USD", "value": amt}})
            print("  paid", p.status_code)
        m["invoices"].append(inv_id)
    os.makedirs("data", exist_ok=True)
    json.dump(m, open("data/seed_manifest.json", "w"), indent=1)


if __name__ == "__main__":
    main()
