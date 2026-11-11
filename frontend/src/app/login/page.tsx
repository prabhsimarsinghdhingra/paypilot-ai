"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errMsg, tokenStore } from "@/lib/api";
import { waitForApi } from "@/lib/wake";

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState(""), [password, setPassword] = useState(""), [name, setName] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [server, setServer] = useState<"checking" | "waking" | "ready" | "down">("checking");
  const check = () => { setServer("checking"); waitForApi(() => setServer(s => (s === "checking" ? "waking" : s))).then(ok => setServer(ok ? "ready" : "down")); };
  useEffect(check, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const r = mode === "login" ? await api.login(email, password) : await api.register(email, password, name); tokenStore.set(r.token); router.replace("/"); }
    catch (err) { setError(errMsg(err)); } finally { setBusy(false); }
  }
  return (
    <div className="login">
      <section className="login-pitch">
        <h1>PayPilot</h1>
        <p>Your PayPal money, explained. Ask what happened, let the assistant draft the follow-ups, and approve each one before anything is sent.</p>
        <p className="fine">Sandbox only. No real money moves.</p>
      </section>
      <form onSubmit={submit} className="login-form" aria-label={mode === "login" ? "Sign in" : "Create account"}>
        <h2>{mode === "login" ? "Sign in" : "Create your account"}</h2>
        {mode === "register" && <label>Name<input value={name} onChange={e => setName(e.target.value)} autoComplete="name" /></label>}
        <label>Email<input type="email" required value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" /></label>
        <label>Password<input type="password" required minLength={8} value={password} onChange={e => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          {mode === "register" && <small>At least 8 characters.</small>}</label>
        {server === "waking" && <p role="status" className="wake">Waking up the demo server… free hosting sleeps when idle, so this can take about a minute.</p>}
        {server === "down" && <p className="err" role="alert">The demo server did not respond. <button type="button" className="link" onClick={check}>Try again</button></p>}
        {error && <p className="err" role="alert">{error}</p>}
        <button className="approve" disabled={busy || server !== "ready"}>{busy ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Need an account? Create one" : "Already registered? Sign in"}</button>
      </form>
    </div>
  );
}
