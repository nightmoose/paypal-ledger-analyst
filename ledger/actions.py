"""Confirm-gated sandbox actions. Proposals are HMAC-signed so the stateless server can
verify on /confirm that the user confirms exactly what the agent proposed."""
from zoneinfo import ZoneInfo
import base64, hashlib, hmac, json, os, time, uuid, datetime as dt
from . import db
from .paypal import call

TTL = 15 * 60


def _key():
    return os.environ.get("APP_SECRET", "dev-only-secret").encode()


def _sign(d: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(d, sort_keys=True).encode()).decode()
    return raw + "." + hmac.new(_key(), raw.encode(), hashlib.sha256).hexdigest()


def verify(token: str) -> dict:
    raw, _, sig = token.rpartition(".")
    if not hmac.compare_digest(sig, hmac.new(_key(), raw.encode(), hashlib.sha256).hexdigest()):
        raise ValueError("bad signature")
    d = json.loads(base64.urlsafe_b64decode(raw))
    if d["exp"] < time.time():
        raise ValueError("proposal expired, ask again")
    return d


def propose(kind: str, ids: list) -> dict:
    ids = list(dict.fromkeys(str(i) for i in ids))[:20]
    q = "','".join(i.replace("'", "") for i in ids)
    if kind == "invoice_reminder":
        res = db.run(f"""SELECT id AS invoice, recipient_email AS recipient, amount, due_date AS due,
            current_date - due_date AS days_overdue FROM invoices
            WHERE id IN ('{q}') AND status NOT IN ('PAID','MARKED_AS_PAID','CANCELLED','DRAFT') ORDER BY due_date""")
        verb, endpoint = "Send reminder to", "POST /v2/invoicing/invoices/{id}/remind"
        noun = "overdue invoice" if all((r[4] or 0) > 0 for r in res["rows"]) else "invoice"
    elif kind == "refund":
        res = db.run(f"""SELECT c.id AS capture, o.customer, c.amount, CAST(c.create_time AS DATE) AS captured
            FROM captures c JOIN orders o ON o.id = c.order_id
            WHERE c.id IN ('{q}') AND c.status = 'COMPLETED' ORDER BY c.create_time""")
        verb, endpoint, noun = "Refund", "POST /v2/payments/captures/{id}/refund", "capture"
    else:
        raise ValueError("unknown action kind")
    valid = [r[0] for r in res["rows"]]
    if not valid:
        raise ValueError("none of the ids are eligible for this action")
    n = len(valid)
    d = {"kind": kind, "ids": valid, "exp": int(time.time()) + TTL, "action_id": "act_" + uuid.uuid4().hex[:8]}
    return {"kind": kind, "title": f"{verb} {n} {noun}{'s' if n != 1 else ''}", "endpoint": endpoint,
            "columns": res["columns"], "rows": res["rows"], "token": _sign(d), "action_id": d["action_id"]}


def execute(token: str, store) -> list:
    d = verify(token)
    now = lambda: dt.datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M:%S ET")
    log = [f"{now()}  confirm received (user click) · action_id {d['action_id']}"]
    ok = 0; logged = 0
    for i in d["ids"]:
        if d["kind"] == "invoice_reminder":
            path = f"/v2/invoicing/invoices/{i}/remind"
            r = call("POST", path, json={"subject": "Friendly reminder: invoice due",
                                         "note": "Just a friendly reminder that this invoice is ready for payment. Thank you!",
                                         "send_to_invoicer": False})
        else:
            path = f"/v2/payments/captures/{i}/refund"
            r = call("POST", path, json={})
        good = r.status_code < 300; ok += good
        log.append(f"{now()}  POST {path}  → {r.status_code} {r.reason_phrase}" + ("" if good else f" {r.text[:160]}"))
        try:
            store.log_action(d["action_id"], d["kind"], i, r.status_code, r.text[:500]); logged += 1
        except Exception as e:
            log.append(f"{now()}  (log write failed: {type(e).__name__})")
    what = "reminders sent" if d["kind"] == "invoice_reminder" else "refunds issued"
    log.append(f"{now()}  done · {ok}/{len(d['ids'])} {what} (sandbox)" + (" · logged to actions table" if logged == len(d["ids"]) else f" · {logged} logged"))
    return log
