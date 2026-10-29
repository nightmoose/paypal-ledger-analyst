from ledger import costguard
from ledger.costguard import MemoryStore


def test_cost_math():
    assert abs(costguard.cost("claude-haiku-4-5", 1_000_000, 0) - 1.0) < 1e-9
    assert abs(costguard.cost("claude-haiku-4-5", 0, 1_000_000) - 5.0) < 1e-9
    assert costguard.cost("unknown-model", 1_000_000, 0) == 3.0  # conservative default


def test_refuses_at_cap():
    s = MemoryStore()
    assert s.gate("1.1.1.1", cap=9.0)["allowed"]
    s.add_spend(8.99, 0, 0, "m")
    assert s.gate("1.1.1.2", cap=9.0)["allowed"]
    s.add_spend(0.01, 0, 0, "m")  # cumulative == 9.00
    g = s.gate("1.1.1.3", cap=9.0)
    assert not g["allowed"] and g["reason"] == "budget"


def test_rate_limit_per_ip():
    s = MemoryStore()
    for _ in range(3):
        assert s.gate("9.9.9.9", per10=3)["allowed"]
    assert s.gate("9.9.9.9", per10=3)["reason"] == "rate"
    assert s.gate("8.8.8.8", per10=3)["allowed"]  # other IPs unaffected


def test_api_refuses_llm_when_budget_spent(monkeypatch):
    from fastapi.testclient import TestClient
    import api.index as idx
    s = MemoryStore(); s.add_spend(9.0, 0, 0, "m"); idx._store = s
    called = []
    monkeypatch.setattr(idx.agent, "ask", lambda *a, **k: called.append(1))
    r = TestClient(idx.app).post("/api/ask", json={"question": "hi"})
    assert r.status_code == 429 and r.json()["reason"] == "budget" and not called
