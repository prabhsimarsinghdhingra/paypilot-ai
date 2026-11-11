"""Capture README / Devpost screenshots from a RUNNING PayPilot, so the images are real and current.

  python scripts/screenshots.py --url http://localhost:3000 --email you@example.com --password '...'      (signs in)
  python scripts/screenshots.py --url https://your-app.vercel.app --email new@example.com --password '...' --register

Needs:  pip install playwright && python -m playwright install chromium.  Use your connected PayPal Sandbox account so the footer says
"PayPal Sandbox" (not the demo simulator). Output: docs/screenshots/*.png"""
import argparse, os
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument("--url", required=True); ap.add_argument("--email", required=True); ap.add_argument("--password", required=True)
ap.add_argument("--register", action="store_true"); ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots"))
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); base = a.url.rstrip("/")


def shot(pg, name, wait=1200):
    pg.wait_for_timeout(wait); path = os.path.join(a.out, f"{name}.png"); pg.screenshot(path=path); print("saved", path)


with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(base + "/login"); pg.wait_for_selector("button.approve:not([disabled])", timeout=130_000)    # waits out a sleeping server
    if not a.register: pg.click("text=Already registered? Sign in")
    pg.fill("input[type=email]", a.email); pg.fill("input[type=password]", a.password); pg.click("button.approve")
    pg.wait_for_selector(".rail", timeout=30_000)
    if pg.locator("text=No payments yet").count():
        pg.click("text=Sync from PayPal")
    pg.wait_for_selector(".figures", timeout=30_000); shot(pg, "01-overview", 2500)
    pg.goto(base + "/transactions"); pg.wait_for_selector(".ag-row .chip", timeout=30_000); shot(pg, "02-transactions")
    pg.click(".ag-row >> nth=0"); shot(pg, "03-transaction-detail", 600)
    pg.goto(base + "/invoices"); pg.wait_for_selector("table.plain tbody tr", timeout=30_000); shot(pg, "04-invoices")
    pg.goto(base + "/studio"); pg.wait_for_selector("[data-testid=owes-scoreboard]", timeout=40_000); shot(pg, "05-studio-dashboard", 3500)
    pg.click("text=Edit dashboard"); pg.wait_for_selector("text=AI Assistant", timeout=20_000); shot(pg, "06-studio-ai-assistant", 2500)
    pg.goto(base + "/approvals"); pg.wait_for_selector("text=Overnight sweep"); shot(pg, "07-approvals")
    pg.goto(base + "/insights"); pg.wait_for_selector("text=Alerts"); shot(pg, "08-forecast-and-alerts", 2500)
    pg.goto(base + "/assistant"); pg.wait_for_selector("text=Ask about your PayPal activity"); shot(pg, "09-assistant")
    b.close()
print("\nDone. For the Devpost gallery also capture a real answer: ask the assistant 'Find overdue invoices and prepare reminders' and screenshot the approval slips yourself.")
