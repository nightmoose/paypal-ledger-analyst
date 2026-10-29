"""Claude agent with two tools: run_sql (read-only) and propose_action (never executes)."""
import json, os
import anthropic
from . import db, costguard, actions

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
MAX_STEPS = 4
SYSTEM = f"""You are PayPal Ledger Analyst, a precise finance analyst for a PayPal sandbox merchant.
Answer questions by calling run_sql with ONE read-only DuckDB SELECT. Always use run_sql before answering with numbers.
{db.SCHEMA_DOC}
Today is current_date in SQL. When a chart helps (time series, categories), set chart_x and chart_y to column names of the final query.
If the user asks to remind invoice recipients or refund a payment, first query the matching ids, then call propose_action.
propose_action never executes anything; the user must click Confirm.
Keep the final answer to 1-3 short sentences. Don't invent data."""

TOOLS = [
    {"name": "run_sql", "description": "Run one read-only DuckDB SELECT over the ledger tables. Returns up to 200 rows.",
     "input_schema": {"type": "object", "properties": {
         "sql": {"type": "string"}, "chart_x": {"type": "string"}, "chart_y": {"type": "string"},
         "chart_title": {"type": "string"}}, "required": ["sql"]}},
    {"name": "propose_action", "description": "Propose a sandbox action for the user to confirm. kind=invoice_reminder takes invoice ids; kind=refund takes capture ids.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["invoice_reminder", "refund"]},
         "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20}}, "required": ["kind", "ids"]}},
]


def ask(question: str, store, client=None) -> dict:
    client = client or anthropic.Anthropic()
    msgs = [{"role": "user", "content": question[:1000]}]
    out = {"answer": "", "result": None, "chart": None, "action": None, "error": None}
    usage_in = usage_out = 0
    try:
        for _ in range(MAX_STEPS):
            r = client.messages.create(model=MODEL, max_tokens=1024, system=SYSTEM, tools=TOOLS, messages=msgs)
            usage_in += r.usage.input_tokens; usage_out += r.usage.output_tokens
            msgs.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in r.content]})
            texts = [b.text for b in r.content if b.type == "text"]
            if texts: out["answer"] = " ".join(texts).strip()
            calls = [b for b in r.content if b.type == "tool_use"]
            if not calls: break
            results = []
            for c in calls:
                try:
                    if c.name == "run_sql":
                        res = db.run(c.input["sql"]); out["result"] = res
                        if c.input.get("chart_x") and c.input.get("chart_y"):
                            out["chart"] = {k: c.input.get("chart_" + k) for k in ("x", "y", "title")}
                        else:
                            out["chart"] = None
                        payload = {"columns": res["columns"], "rows": res["rows"][:50], "row_count": len(res["rows"])}
                    else:
                        out["action"] = actions.propose(c.input["kind"], c.input["ids"])
                        payload = {"proposed": out["action"]["title"], "note": "waiting for user Confirm"}
                    results.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(payload, default=str)})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": c.id, "content": f"error: {e}", "is_error": True})
            msgs.append({"role": "user", "content": results})
    finally:
        usd = costguard.cost(MODEL, usage_in, usage_out)
        if usage_in or usage_out:
            out["spent_total"] = store.add_spend(usd, usage_in, usage_out, MODEL)
        out["tokens"] = {"in": usage_in, "out": usage_out}
    return out
