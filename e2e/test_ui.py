"""Browser tests of the real Next.js app against the real FastAPI app (PayPal = labeled demo simulator, Gemini = rule-based stand-in)."""
import csv, io
from playwright.sync_api import expect
from conftest import WEB


def go(page, label):
    page.click(f".rail >> text={label}")


def test_unauthenticated_users_are_sent_to_login(page):
    page.goto(WEB + "/transactions"); page.wait_for_url("**/login")


def test_register_empty_state_then_sync_shows_real_numbers(user):
    assert "DEMO SIMULATOR" in user.inner_text(".rail-foot")  # never pass the simulator off as PayPal
    figures = user.inner_text(".figures")
    assert "Revenue" in figures and "Failed" in figures
    assert "overdue invoice" in user.inner_text(".attention")
    assert user.locator(".tabs button").count() == 2  # USD and EUR are never merged into one number
    assert user.errors == []


def test_grid_filters_sorts_paginates_and_exports_server_side(user):
    go(user, "Transactions")
    expect(user.locator(".ag-row .chip")).to_have_count(50, timeout=15000)  # waits for real data, not loading placeholders
    total_text = user.inner_text(".page-head .sub")
    user.select_option(".filters select >> nth=0", "D")
    expect(user.locator(".page-head .sub")).not_to_have_text(total_text, timeout=10000)
    expect(user.locator(".ag-row .chip").first).to_have_text("Failed", timeout=10000)
    assert set(user.locator(".ag-row .chip").all_inner_texts()) == {"Failed"}
    user.select_option(".filters select >> nth=0", ""); user.fill(".filters input[type=search]", "initech"); user.wait_for_timeout(900)
    assert all("Initech" in t for t in user.locator(".ag-row [col-id=payer_name]").all_inner_texts())
    user.fill(".filters input[type=search]", ""); user.wait_for_timeout(600)
    user.click(".ag-header-cell[col-id=amount]"); user.wait_for_timeout(700)
    vals = [float("".join(c for c in t if c.isdigit() or c == ".")) for t in user.locator(".ag-row [col-id=amount]").all_inner_texts()[:5]]
    assert vals == sorted(vals)
    user.click(".ag-row >> nth=0"); user.wait_for_selector(".drawer"); assert "PayPal transaction ID" in user.inner_text(".drawer")
    with user.expect_download() as d: user.click("text=Export CSV")
    rows = list(csv.reader(io.StringIO(open(d.value.path(), encoding="utf-8").read())))
    assert rows[0][:2] == ["Date", "Transaction ID"] and len(rows) > 50


def test_headline_flow_overdue_reminders_approve_and_reject(user):
    go(user, "Assistant"); user.click("text=Find overdue invoices and prepare reminders")
    user.wait_for_selector(".slip"); assert user.locator(".slip").count() == 2
    assert "Looked up overdue invoices" in user.inner_text(".tools") and "needs approval" in user.inner_text(".tools")
    assert all("Waiting for you" in s for s in user.locator(".slip .state").all_inner_texts())
    user.locator(".slip >> nth=0").get_by_text("Approve and run").click(); user.wait_for_selector(".slip.completed")
    assert "invoice is now" in user.inner_text(".slip.completed")
    user.locator(".slip.pending").get_by_text("Reject").click(); user.wait_for_selector(".slip.rejected")
    go(user, "Approvals"); user.wait_for_selector("text=Audit log")
    log = user.inner_text("table.plain")
    assert "proposed" in log and "approved" in log and "executed" in log and "rejected" in log


def test_invoice_draft_is_not_sent_until_approved(user):
    go(user, "Invoices"); user.wait_for_selector("table.plain tbody tr")
    user.fill("input[type=email]", "new@customer.example"); user.fill("fieldset input >> nth=0", "Consulting")
    user.fill("fieldset input[type=number] >> nth=0", "2"); user.fill("fieldset input[type=number] >> nth=1", "100"); user.fill("fieldset input[type=number] >> nth=2", "10")
    user.wait_for_selector(".preview strong"); assert "220" in user.inner_text(".preview")
    user.click("text=Save as draft"); user.wait_for_selector("text=It has not been sent")
    row = user.locator("table.plain tbody tr", has_text="new@customer.example"); assert "DRAFT" in row.inner_text()
    row.get_by_text("Request send").click(); user.wait_for_selector("text=Queued for your approval")
    go(user, "Approvals"); user.wait_for_selector(".slip.pending"); assert "Send invoice to customer" in user.inner_text(".slip.pending")
    send = user.locator(".slip", has_text="Send invoice to customer"); send.get_by_text("Approve and run").click()
    send.locator(".okline").wait_for(); assert "SENT" in send.inner_text()


def test_forecast_and_alerts_page(user):
    go(user, "Forecast & alerts"); user.wait_for_selector(".alerts li")
    assert "revenue" in user.inner_text(".alerts").lower() and user.locator(".alerts li .sev").count() >= 2
    assert "not guaranteed" in user.inner_text("body").lower() or "not promises" in user.inner_text("body").lower()


def test_bad_login_shows_an_error(page):
    page.goto(WEB + "/login"); page.click("text=Already registered? Sign in")
    page.fill("input[type=email]", "nobody@example.com"); page.fill("input[type=password]", "wrongpassword"); page.click("button.approve")
    expect(page.locator("p.err[role=alert]")).to_contain_text("Invalid", timeout=10000)  # not bare [role=alert]: Next.js has its own empty route announcer


def test_studio_dashboard_matches_overview_numbers_and_never_mixes_currencies(user):
    def digits(t): return "".join(c for c in t if c.isdigit() or c == ".")
    overview_rev = str(int(float(digits(user.locator(".figures strong").first.inner_text()))))  # whole-number part: Studio may round cents differently
    go(user, "Analytics Studio"); user.wait_for_selector("[studio-id=paypilot-studio]"); user.wait_for_timeout(3500)
    studio = user.inner_text("[studio-id=paypilot-studio]")
    assert "Revenue" in studio and "Revenue by month" in studio and "Transactions" in studio
    assert overview_rev in digits(studio.replace(",", ""))  # same revenue from two independent code paths
    user.click(".studio-page >> role=tab[name=EUR]"); user.wait_for_timeout(3500)
    eur = digits(user.inner_text("[studio-id=paypilot-studio]").replace(",", ""))
    assert overview_rev not in eur  # switching currency swaps the dataset instead of adding EUR to USD
    user.click("text=Edit dashboard"); user.wait_for_selector("text=Compose"); assert "Data" in user.inner_text("[studio-id=paypilot-studio]")


def test_studio_ai_assistant_round_trips_through_our_backend(user):
    """AG Studio's own agent framework -> our adapter -> /ai/studio-turn -> (stand-in for Gemini) -> reply in Studio's chat panel."""
    import json, urllib.request
    from conftest import API
    go(user, "Analytics Studio"); user.wait_for_selector("[studio-id=paypilot-studio]"); user.click("text=Edit dashboard")
    user.wait_for_selector("text=AI Assistant")
    box = user.locator("[studio-id=paypilot-studio] textarea").first; box.click(); box.fill("Show me revenue by customer")
    user.click("[aria-label='Send message']")
    expect(user.locator("[studio-id=paypilot-studio]")).to_contain_text("Hello from the PayPilot test model", timeout=15000)
    turns = json.load(urllib.request.urlopen(API.replace("/api/v1", "") + "/__test__/studio-log"))
    assert turns and "delegate_to" in turns[-1]["tools"] and "view_schema" in turns[-1]["tools"]   # Studio's lead agent and its tools reached the model
    assert {"list_overdue_invoices", "queue_payment_reminder"} <= set(turns[-1]["tools"])          # our PayPilot tools sit beside Studio's own
    assert user.errors == []


def test_studio_scoreboard_widget_queues_a_nudge_for_approval_not_sends_it(user):
    go(user, "Analytics Studio"); user.wait_for_selector("[studio-id=paypilot-studio]")
    board = user.locator("[data-testid=owes-scoreboard]"); expect(board).to_be_visible(timeout=15000)
    expect(board.locator("li")).to_have_count(3)                       # the three overdue USD invoices, worst first
    assert "Hooli Media" in board.locator("li").first.inner_text() and "days late" in board.inner_text()
    board.get_by_role("button", name="Draft a nudge").first.click()
    expect(board).to_contain_text("Queued. Approve it in Approvals", timeout=10000)
    go(user, "Approvals"); user.wait_for_selector(".slip.pending")
    slip = user.locator(".slip.pending", has_text="Send payment reminder"); assert slip.count() == 1 and "Waiting for you" in slip.inner_text()   # queued, NOT sent


def test_login_shows_waking_message_while_a_sleeping_server_boots_then_works(page):
    """Free Render hosting sleeps when idle. Simulate a cold start: the first /health calls fail, then succeed."""
    calls = {"n": 0}
    def flaky(route):
        calls["n"] += 1
        route.abort() if calls["n"] <= 2 else route.continue_()
    page.route("**/health", flaky)
    page.goto(WEB + "/login")
    expect(page.locator("p.wake")).to_contain_text("Waking up the demo server", timeout=8000)
    expect(page.locator("button.approve")).to_be_disabled()                    # no confusing failed login while it boots
    expect(page.locator("p.wake")).to_have_count(0, timeout=20000)
    expect(page.locator("button.approve")).to_be_enabled()


def test_overnight_sweep_prepares_reminders_for_approval_and_sends_nothing(user):
    go(user, "Approvals"); user.wait_for_selector("text=Overnight sweep")
    assert user.locator(".slip.pending").count() == 0
    user.get_by_role("button", name="Run sweep now").click()
    expect(user.locator(".sweep [role=status]")).to_contain_text("Queued 3 reminders for your approval", timeout=15000)
    assert "Ran inline" in user.inner_text(".sweep")                                   # honest about where it ran (no Render workflow in tests)
    expect(user.locator(".slip.pending")).to_have_count(3, timeout=10000)
    assert "Prepared by the overnight sweep" in user.locator(".slip.pending").first.inner_text()
    user.get_by_role("button", name="Run sweep now").click()
    expect(user.locator(".sweep [role=status]")).to_contain_text("Queued 0 reminders", timeout=15000); expect(user.locator(".slip.pending")).to_have_count(3)   # running it again never duplicates
