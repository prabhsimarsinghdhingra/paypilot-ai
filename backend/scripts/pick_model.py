"""Find a Gemini model that works for YOUR key and is fast right now.   Run from backend/:   python scripts/pick_model.py
Lists the Flash models your key can use, times a tiny call and a tool-calling call on each, and prints the .env lines to use."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKIP = ("image", "tts", "live", "audio", "embedding", "robotics", "computer", "exp")


def candidates(client, limit=8):
    names = set()
    for m in client.models.list():
        acts = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
        n = m.name.replace("models/", "")
        if "generateContent" in acts and "flash" in n and not any(x in n for x in SKIP): names.add(n)
    return sorted(names, reverse=True)[:limit]  # newest-looking names first


def probe(client, model, types, clock=time.perf_counter):
    out = {"model": model, "simple": None, "tool_ok": False, "error": ""}
    try:
        t = clock(); client.models.generate_content(model=model, contents="Reply with the single word: ok"); out["simple"] = clock() - t
        decl = types.FunctionDeclaration(name="get_failed_payments", description="Count failed payments", parameters={"type": "object", "properties": {"days": {"type": "integer"}}})
        cfg = types.GenerateContentConfig(tools=[types.Tool(function_declarations=[decl])], automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        t = clock(); r = client.models.generate_content(model=model, contents="How many payments failed in the last 30 days? Use the tool.", config=cfg)
        parts = (r.candidates[0].content.parts or []) if r.candidates else []
        out["tool_ok"] = any(getattr(p, "function_call", None) for p in parts); out["tool_secs"] = clock() - t
    except Exception as e:
        out["error"] = f"{getattr(e, 'code', '')} {str(getattr(e, 'message', e))[:90]}".strip()
    return out


def recommend(results):
    good = sorted([r for r in results if r["tool_ok"]], key=lambda r: r["simple"] + r.get("tool_secs", 0))
    return good


def main():
    from app.core.config import settings as s
    from google import genai
    from google.genai import types
    if not s.gemini_api_key: sys.exit("GEMINI_API_KEY is not set in .env")
    client = genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(timeout=25_000))
    try: names = candidates(client)
    except Exception as e: sys.exit(f"Could not list models: {getattr(e, 'code', '')} {str(getattr(e, 'message', e))[:150]}  (is the key valid?)")
    print(f"{len(names)} Flash model(s) available to your key. Testing each (up to ~50 s per model)...\n")
    results = []
    for n in names:
        r = probe(client, n, types); results.append(r)
        status = f"{r['simple']:.1f}s + tool {r.get('tool_secs', 0):.1f}s, tool-calling {'OK' if r['tool_ok'] else 'NO'}" if r["simple"] is not None else f"FAILED {r['error']}"
        print(f"  {n:<34} {status}" + (f"  [{r['error']}]" if r["simple"] is not None and r["error"] else ""))
    good = recommend(results)
    if not good: sys.exit("\nNo model passed. If errors are 503/504, Google is overloaded: wait a few minutes and run this again.")
    print("\nPut this in backend/.env, then restart the backend:\n")
    print(f"GEMINI_MODEL={good[0]['model']}")
    if len(good) > 1: print(f"GEMINI_FALLBACK_MODELS={','.join(r['model'] for r in good[1:3])}")


if __name__ == "__main__": main()
