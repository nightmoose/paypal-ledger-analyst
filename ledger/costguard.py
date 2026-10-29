"""Persistent spend tracking + per-IP rate limit (Supabase RPC; in-memory store for tests/local)."""
import os, time
import httpx

PRICE = {  # USD per million tokens (input, output)
    "claude-haiku-4-5": (1.0, 5.0),
}
CAP_USD = float(os.environ.get("SPEND_CAP_USD", "9.0"))
PER_10MIN = int(os.environ.get("RATE_PER_10MIN", "8"))
PER_DAY = int(os.environ.get("RATE_PER_DAY", "40"))


def cost(model: str, in_tok: int, out_tok: int) -> float:
    pi, po = PRICE.get(model, (3.0, 15.0))  # unknown model: assume a pricier tier
    return (in_tok * pi + out_tok * po) / 1e6


class MemoryStore:
    def __init__(self):
        self.spend, self.hits, self.actions = [], [], []

    def gate(self, ip, cap=CAP_USD, per10=PER_10MIN, perday=PER_DAY):
        spent = sum(self.spend)
        if spent >= cap: return {"allowed": False, "reason": "budget", "spent": spent}
        now = time.time()
        h = [t for i, t in self.hits if i == ip]
        if sum(t > now - 600 for t in h) >= per10 or sum(t > now - 86400 for t in h) >= perday:
            return {"allowed": False, "reason": "rate", "spent": spent}
        self.hits.append((ip, now)); return {"allowed": True, "spent": spent}

    def add_spend(self, usd, i, o, model):
        self.spend.append(usd); return sum(self.spend)

    def log_action(self, *a):
        self.actions.append(a)


class SupabaseStore:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/"
        k = os.environ["SUPABASE_ANON_KEY"]
        self.h = {"apikey": k, "Authorization": f"Bearer {k}"}
        self.secret = os.environ["APP_SECRET"]

    def _rpc(self, fn, **kw):
        r = httpx.post(self.url + fn, headers=self.h, json={"p_secret": self.secret, **kw}, timeout=15)
        r.raise_for_status()
        return r.json() if r.content else None

    def gate(self, ip, cap=CAP_USD, per10=PER_10MIN, perday=PER_DAY):
        return self._rpc("pla_gate", p_ip=ip, p_cap=cap, p_per_10min=per10, p_per_day=perday)

    def add_spend(self, usd, i, o, model):
        return self._rpc("pla_add_spend", p_usd=usd, p_in=i, p_out=o, p_model=model)

    def log_action(self, action_id, kind, target, status, detail):
        self._rpc("pla_log_action", p_action_id=action_id, p_kind=kind, p_target=target, p_status=status, p_detail=detail)


def default_store():
    return SupabaseStore() if os.environ.get("SUPABASE_URL") else MemoryStore()
