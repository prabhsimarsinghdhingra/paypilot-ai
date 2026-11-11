import os, shutil, subprocess, sys, tempfile, time, urllib.request, uuid
import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_PORT, WEB_PORT = 8765, 3765
API = f"http://localhost:{BACKEND_PORT}/api/v1"; WEB = f"http://localhost:{WEB_PORT}"


def wait(url, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try: urllib.request.urlopen(url, timeout=2); return
        except Exception: time.sleep(0.7)
    raise RuntimeError(f"{url} did not come up")


@pytest.fixture(scope="session")
def servers():
    tmp = tempfile.mkdtemp(); fe = os.path.join(ROOT, "frontend"); npm = shutil.which("npm")
    build_env = {**os.environ, "NEXT_PUBLIC_API_URL": API, "NEXT_DIST_DIR": ".next-e2e"}
    subprocess.run([npm, "run", "build"], cwd=fe, env=build_env, check=True, capture_output=True)
    be_env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp}/e2e.db", "FORCE_DEMO_PAYPAL": "true", "FRONTEND_URL": WEB, "GEMINI_API_KEY": "unused", "APP_ENV": "development"}
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "fake_server:app", "--port", str(BACKEND_PORT)], cwd=os.path.join(ROOT, "e2e"), env=be_env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen([shutil.which("node"), os.path.join(fe, "node_modules", "next", "dist", "bin", "next"), "start", "-p", str(WEB_PORT)], cwd=fe, env=build_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait(f"http://localhost:{BACKEND_PORT}/health"); wait(WEB + "/login")
        yield
    finally:
        for p in (web, backend): p.terminate()
        for p in (web, backend):
            try: p.wait(10)
            except Exception: p.kill()


@pytest.fixture(scope="session")
def browser(servers):
    with sync_playwright() as pw:
        b = pw.chromium.launch(); yield b; b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1360, "height": 900}, accept_downloads=True); pg = ctx.new_page()
    pg.errors = []; pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


@pytest.fixture
def user(page):
    """A freshly registered, signed-in user with synced demo data."""
    page.goto(WEB + "/login"); page.fill("input[type=email]", f"e2e-{uuid.uuid4().hex[:8]}@example.com"); page.fill("input[type=password]", "password123")
    page.click("button.approve"); page.wait_for_selector("text=No payments yet")
    page.click("text=Sync from PayPal"); page.wait_for_selector("text=Needs your attention")
    return page
