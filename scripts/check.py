#!/usr/bin/env python3
"""One command to verify everything locally.

  python scripts/check.py            fast: secrets scan, lint, backend tests, frontend typecheck
  python scripts/check.py --full     also builds the frontend and runs the browser end-to-end tests
  python scripts/check.py --live     also runs the live doctor against your real PayPal Sandbox + Gemini keys (needs backend/.env)

Run it from the repo root with the backend venv active."""
import argparse, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BE, FE = os.path.join(ROOT, "backend"), os.path.join(ROOT, "frontend")
ap = argparse.ArgumentParser(); ap.add_argument("--full", action="store_true"); ap.add_argument("--live", action="store_true"); args = ap.parse_args()
npm, npx = shutil.which("npm"), shutil.which("npx")
results = []


def step(name, cmd, cwd=ROOT, optional_tool=None):
    if optional_tool and not shutil.which(optional_tool) and not optional_tool.startswith("py:"):
        results.append((name, None, 0, f"{optional_tool} not installed")); return
    t = time.time(); p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    ok = p.returncode == 0; results.append((name, ok, time.time() - t, ""))
    if not ok: print(f"\n----- {name} FAILED -----\n{(p.stdout + p.stderr)[-2500:]}")


step("secrets scan", [sys.executable, "scripts/check_secrets.py"])
step("lint (syntax, undefined names)", [sys.executable, "-m", "ruff", "check", "--select", "E9,F", "app", "tests", "scripts"], BE)
step("backend tests", [sys.executable, "-m", "pytest", "-q"], BE)
if npx and os.path.isdir(os.path.join(FE, "node_modules")): step("frontend typecheck", [npx, "tsc", "--noEmit"], FE)
else: results.append(("frontend typecheck", None, 0, "run `npm install` in frontend/ first"))
if args.full:
    step("frontend production build", [npm, "run", "build"], FE)
    step("browser end-to-end tests", [sys.executable, "-m", "pytest", "e2e", "-q"], ROOT)
if args.live: step("LIVE doctor (PayPal Sandbox + Gemini)", [sys.executable, "scripts/doctor.py"], BE)

print("\n" + "=" * 58)
for name, ok, secs, note in results:
    print(f"  {'PASS' if ok else 'SKIP' if ok is None else 'FAIL'}  {name:<42} {secs:5.1f}s  {note}")
failed = [r for r in results if r[1] is False]
print("=" * 58 + ("\nAll checks passed." if not failed else f"\n{len(failed)} check(s) failed."))
if not args.live: print("Tip: run with --full for build + browser tests, --live to test your real keys.")
sys.exit(1 if failed else 0)
