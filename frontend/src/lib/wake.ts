import { API_BASE } from "./api";

/** Free Render services sleep after 15 idle minutes and take ~1 minute to wake. Poll /health until the API answers,
 *  calling onWaiting() if it is not instant, so visitors see "waking up" instead of a broken page. */
export async function waitForApi(onWaiting: () => void, maxMs = 120_000, pause = 2500): Promise<boolean> {
  const health = API_BASE.replace(/\/api\/v1\/?$/, "") + "/health";
  const start = Date.now();
  const timer = setTimeout(onWaiting, 1500);
  try {
    while (Date.now() - start < maxMs) {
      try {
        const r = await fetch(health, { cache: "no-store", signal: AbortSignal.timeout(8000) });
        if (r.ok && (await r.json()).status === "ok") return true;  // Render's own loading page is not our JSON
      } catch { /* still asleep or unreachable */ }
      await new Promise(res => setTimeout(res, pause));
    }
    return false;
  } finally { clearTimeout(timer); }
}
