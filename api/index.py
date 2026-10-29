import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from ledger import agent, actions, costguard

app = FastAPI(title="PayPal Ledger Analyst")
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html")
_store = None


def store():
    global _store
    _store = _store or costguard.default_store()
    return _store


def client_ip(req: Request) -> str:
    return (req.headers.get("x-real-ip") or req.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (req.client.host if req.client else "unknown"))


class Ask(BaseModel):
    question: str


class Confirm(BaseModel):
    token: str


@app.get("/", response_class=HTMLResponse)
def index():
    return open(STATIC).read()


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "sandbox"}


@app.post("/api/ask")
def ask(body: Ask, req: Request):
    g = store().gate(client_ip(req))
    if not g.get("allowed"):
        msg = ("The demo's AI budget for this event has been fully used. Thanks for trying it! Run it locally with your own key (see README)."
               if g.get("reason") == "budget" else "You're asking quickly! Please wait a few minutes and try again.")
        return JSONResponse({"error": msg, "reason": g.get("reason")}, status_code=429)
    try:
        out = agent.ask(body.question, store())
    except Exception as e:
        return JSONResponse({"error": f"Agent error: {type(e).__name__}"}, status_code=500)
    out.pop("spent_total", None)
    return out


@app.post("/api/confirm")
def confirm(body: Confirm):
    try:
        return {"log": actions.execute(body.token, store())}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
