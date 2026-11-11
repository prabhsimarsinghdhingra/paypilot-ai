"""Fails if a real-looking secret is in any file that would be committed. Run before every push:  python scripts/check_secrets.py"""
import os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = [(r"AIza[0-9A-Za-z\-_]{35}", "Google API key"), (r"AQ\.[A-Za-z0-9_\-]{30,}", "Google/Vertex API key"),
            (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"), (r"A[A-Za-z0-9_\-]{70,90}", "possible PayPal client id/secret (long token)"),
            (r"(?im)^[ \t]*(PAYPAL_CLIENT_SECRET|GEMINI_API_KEY|JWT_SECRET|ENCRYPTION_KEY)[ \t]*=[ \t]*(?!change-me|your-|<)\S{12,}", "secret assigned in a tracked file")]
SKIP_DIRS = {"node_modules", ".next", ".next-e2e", ".git", ".venv", "__pycache__", ".pytest_cache"}
SKIP_EXT = {".png", ".jpg", ".ico", ".db", ".zip", ".lock"}

def files():
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        return [os.path.join(ROOT, f) for f in out if f]
    except Exception:
        return [os.path.join(d, f) for d, ds, fs in os.walk(ROOT) if not (set(d.split(os.sep)) & SKIP_DIRS) for f in fs]

hits = []
for p in files():
    if os.path.splitext(p)[1] in SKIP_EXT or not os.path.isfile(p) or (set(p.split(os.sep)) & SKIP_DIRS): continue
    name = os.path.basename(p)
    if name.startswith(".env") and not name.endswith(".example"): hits.append((p, 0, "an .env file would be committed")); continue
    try: text = open(p, encoding="utf-8").read()
    except Exception: continue
    if name == "package-lock.json": continue
    for pat, label in PATTERNS:
        for m in re.finditer(pat, text):
            hits.append((p, text[:m.start()].count("\n") + 1, label))
if hits:
    for p, ln, label in hits: print(f"LEAK? {os.path.relpath(p, ROOT)}:{ln}  {label}")
    print(f"\n{len(hits)} possible secret(s). Remove them and rotate the key.")
    sys.exit(1)
print("No secrets found.")
