"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import {
  apiAdminCost,
  apiAdminDeleteDocument,
  apiAdminDemoQuestions,
  apiAdminDocuments,
  apiAdminFeedback,
  apiAdminHealth,
  apiAdminLlmSettings,
  apiAdminPatchLlmSettings,
  apiAdminPatchUser,
  apiAdminStats,
  apiAdminUsers,
  apiLogin,
  type AuthUser,
  type LlmSettings,
} from "@/lib/api";

type Tab =
  | "pending"
  | "users"
  | "feedback"
  | "docs"
  | "stats"
  | "cost"
  | "health"
  | "demo"
  | "llm";

async function settled<T>(p: Promise<T>, fallback: T): Promise<{ ok: boolean; value: T; err?: string }> {
  try {
    return { ok: true, value: await p };
  } catch (e) {
    return { ok: false, value: fallback, err: e instanceof Error ? e.message : String(e) };
  }
}

export default function AdminPage() {
  const { user, ready, logout, login } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [cost, setCost] = useState<Record<string, unknown> | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [demo, setDemo] = useState<{ count: number; items: any[] } | null>(null);
  const [llm, setLlm] = useState<LlmSettings | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [docs, setDocs] = useState<any[]>([]);
  const [feedback, setFeedback] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [tab, setTab] = useState<Tab>("llm");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [adminEmail, setAdminEmail] = useState("admin@civic.ai");
  const [adminPass, setAdminPass] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);

  const pending = useMemo(
    () => users.filter((u) => !u.approved && u.role !== "admin"),
    [users]
  );

  async function refresh(t: string) {
    const results = await Promise.all([
      settled(apiAdminStats(t), null as Record<string, unknown> | null),
      settled(apiAdminCost(t), null as Record<string, unknown> | null),
      settled(apiAdminUsers(t), [] as any[]),
      settled(apiAdminDocuments(t), [] as any[]),
      settled(apiAdminFeedback(t), [] as any[]),
      settled(apiAdminHealth(t), null as Record<string, unknown> | null),
      settled(apiAdminDemoQuestions(t), null as { count: number; items: any[] } | null),
      settled(apiAdminLlmSettings(t), null as LlmSettings | null),
    ]);
    const [s, c, u, d, f, h, dq, ls] = results;
    setStats(s.value);
    setCost(c.value);
    setUsers(u.value);
    setDocs(d.value);
    setFeedback(f.value);
    setHealth(h.value);
    setDemo(dq.value);
    setLlm(ls.value);
    const errs = results
      .filter((r) => !r.ok)
      .map((r) => r.err || "request failed");
    setPartialErrors(errs);
    if (errs.length === results.length) {
      throw new Error(errs[0] || "Admin load failed");
    }
    setError("");
  }

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      setLoaded(true);
      return;
    }
    if (user.role !== "admin") {
      setError(
        `Contul ${user.email} are rol „${user.role}”. Autentifică-te ca admin@civic.ai.`
      );
      setLoaded(true);
      return;
    }
    void refresh(user.access_token)
      .then(() => setLoaded(true))
      .catch((e) => {
        setError(
          e instanceof Error
            ? e.message
            : "Nu am putut încărca panoul admin (token invalid sau API oprit)."
        );
        setLoaded(true);
      });
  }, [ready, user]);

  async function doAdminLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoginBusy(true);
    setError("");
    try {
      const u: AuthUser = await apiLogin(adminEmail.trim(), adminPass);
      if (u.role !== "admin") {
        setError(`Contul ${u.email} nu este admin.`);
        return;
      }
      login(u);
      setLoaded(false);
      await refresh(u.access_token);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Autentificare eșuată");
    } finally {
      setLoginBusy(false);
    }
  }

  async function approve(id: number, approved: boolean) {
    if (!user) return;
    setBusyId(id);
    try {
      await apiAdminPatchUser(user.access_token, id, { approved });
      await refresh(user.access_token);
      setToast(approved ? "Utilizator aprobat" : "Acces revocat");
      setTimeout(() => setToast(""), 2200);
    } finally {
      setBusyId(null);
    }
  }

  async function saveLlm(patch: {
    provider?: "local" | "groq";
    groq_model?: string;
    local_model?: string;
  }) {
    if (!user) return;
    setLlmBusy(true);
    setError("");
    try {
      const next = await apiAdminPatchLlmSettings(user.access_token, patch);
      setLlm(next);
      setToast(
        next.provider === "groq"
          ? `LLM: Groq · ${next.groq_model}`
          : `LLM: Local · ${next.local_model}`
      );
      setTimeout(() => setToast(""), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Salvare LLM eșuată");
    } finally {
      setLlmBusy(false);
    }
  }

  if (!ready || !loaded) {
    return <div className="boot-screen">CivicAI</div>;
  }

  if (!user || user.role !== "admin") {
    return (
      <div className="admin-shell">
        <div className="admin-wrap" style={{ maxWidth: 420 }}>
          <Link href="/" className="muted">
            ← Înapoi la chat
          </Link>
          <h1 style={{ marginTop: 12 }}>Administrare</h1>
          {error && (
            <div className="err" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
          <p className="muted" style={{ marginTop: 12, lineHeight: 1.5 }}>
            Panoul admin necesită contul <code>admin@civic.ai</code>. Dacă ești
            logat ca cetățean, autentifică-te mai jos.
          </p>
          <form onSubmit={doAdminLogin} style={{ marginTop: 16, display: "grid", gap: 10 }}>
            <label>
              Email
              <input
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                autoComplete="username"
              />
            </label>
            <label>
              Parolă
              <input
                type="password"
                value={adminPass}
                onChange={(e) => setAdminPass(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" className="btn" disabled={loginBusy}>
              {loginBusy ? "…" : "Intră ca admin"}
            </button>
          </form>
          {user && (
            <button
              type="button"
              className="btn-ghost"
              style={{ marginTop: 12 }}
              onClick={() => {
                logout();
                router.refresh();
              }}
            >
              Deconectează {user.email}
            </button>
          )}
        </div>
      </div>
    );
  }

  const token = user.access_token;

  return (
    <div className="admin-shell">
      <div className="admin-wrap">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <Link href="/" className="muted">
            ← Înapoi la chat
          </Link>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="muted" style={{ fontSize: 13 }}>
              {user.email}
            </span>
            <button type="button" className="btn-ghost" onClick={() => logout()}>
              Logout
            </button>
          </div>
        </div>
        <h1 style={{ marginTop: 8 }}>Administrare</h1>
        {error && <div className="err">{error}</div>}
        {partialErrors.length > 0 && (
          <div className="err" style={{ opacity: 0.85 }}>
            Unele endpoint-uri au eșuat: {partialErrors.join("; ")}
          </div>
        )}
        {toast && <div className="toast">{toast}</div>}

        <div className="admin-tabs">
          {(
            [
              ["llm", "LLM / Setări"],
              ["pending", `În așteptare (${pending.length})`],
              ["users", `Utilizatori (${users.length})`],
              ["feedback", `Feedback (${feedback.length})`],
              ["docs", `Documente (${docs.length})`],
              ["stats", "Stats"],
              ["cost", "Cost"],
              ["health", "Health"],
              ["demo", "Demo Q"],
            ] as [Tab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tab === id ? "chip on" : "chip"}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => void refresh(token).catch((e) => setError(String(e)))}
          >
            Reîncarcă
          </button>
        </div>

        {tab === "pending" && (
          <div className="admin-list">
            {pending.length === 0 ? (
              <p className="muted">Niciun utilizator în așteptare.</p>
            ) : (
              pending.map((u) => (
                <div key={u.id} className="admin-row">
                  <div>
                    <strong>{u.email}</strong>
                    <div className="muted">
                      {u.role} · creat {u.created_at || "—"}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn"
                    disabled={busyId === u.id}
                    onClick={() => void approve(u.id, true)}
                  >
                    Aprobă
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {tab === "users" && (
          <div className="admin-list">
            {users.length === 0 ? (
              <p className="muted">Niciun utilizator încărcat.</p>
            ) : (
              users.map((u) => (
                <div key={u.id} className="admin-row">
                  <div>
                    <strong>{u.email}</strong>
                    <div className="muted">
                      {u.role} · {u.approved ? "aprobat" : "neaprobat"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {!u.approved && u.role !== "admin" && (
                      <button
                        type="button"
                        className="btn"
                        disabled={busyId === u.id}
                        onClick={() => void approve(u.id, true)}
                      >
                        Aprobă
                      </button>
                    )}
                    {u.approved && u.role !== "admin" && (
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={busyId === u.id}
                        onClick={() => void approve(u.id, false)}
                      >
                        Revocă
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {tab === "feedback" && (
          <div className="admin-list">
            {feedback.length === 0 ? (
              <p className="muted">Niciun feedback încă.</p>
            ) : (
              feedback.map((f) => (
                <div key={f.id} className="admin-row" style={{ alignItems: "flex-start" }}>
                  <div>
                    <strong>{f.useful ? "👍 util" : "👎 inutil"}</strong>
                    {f.reason && <span className="muted"> · {f.reason}</span>}
                    <div style={{ marginTop: 6 }}>{f.question}</div>
                    {f.detail && <div className="muted">{f.detail}</div>}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {tab === "docs" && (
          <div className="admin-list">
            {docs.map((d) => (
              <div key={d.id} className="admin-row">
                <div>
                  <strong>{d.title}</strong>
                  <div className="muted">{d.url}</div>
                </div>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() =>
                    void apiAdminDeleteDocument(token, d.id).then(() => refresh(token))
                  }
                >
                  Șterge
                </button>
              </div>
            ))}
          </div>
        )}

        {tab === "stats" && stats && (
          <pre className="admin-pre">{JSON.stringify(stats, null, 2)}</pre>
        )}
        {tab === "cost" && cost && (
          <pre className="admin-pre">{JSON.stringify(cost, null, 2)}</pre>
        )}
        {tab === "health" && health && (
          <pre className="admin-pre">{JSON.stringify(health, null, 2)}</pre>
        )}
        {tab === "demo" && demo && (
          <div>
            <p className="muted">{demo.count} întrebări demo</p>
            <pre className="admin-pre">{JSON.stringify(demo.items?.slice(0, 8), null, 2)}</pre>
          </div>
        )}

        {tab === "llm" && (
          <div className="admin-list" style={{ gap: 16 }}>
            {!llm ? (
              <p className="muted">Nu am putut încărca setările LLM.</p>
            ) : (
              <>
                <div className="admin-row" style={{ alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <strong>Provider răspunsuri</strong>
                    <p className="muted" style={{ marginTop: 6, lineHeight: 1.45 }}>
                      Alege modelul local (Ollama pe acest PC) sau Groq Cloud
                      (API OpenAI-compatible). Schimbarea se aplică imediat la
                      chat.
                    </p>
                    <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className={llm.provider === "local" ? "chip on" : "chip"}
                        disabled={llmBusy}
                        onClick={() => void saveLlm({ provider: "local" })}
                      >
                        Local (Ollama)
                      </button>
                      <button
                        type="button"
                        className={llm.provider === "groq" ? "chip on" : "chip"}
                        disabled={llmBusy || !llm.groq_api_key_set}
                        title={
                          llm.groq_api_key_set
                            ? "Folosește Groq Cloud"
                            : "Setează GROQ_API_KEY în .env"
                        }
                        onClick={() => void saveLlm({ provider: "groq" })}
                      >
                        Groq Cloud
                      </button>
                    </div>
                    <p className="muted" style={{ marginTop: 10, fontSize: 13 }}>
                      Activ:{" "}
                      <strong>
                        {llm.provider === "groq"
                          ? `Groq · ${llm.groq_model}`
                          : `Local · ${llm.local_model}`}
                      </strong>
                    </p>
                  </div>
                </div>

                <div className="admin-row" style={{ alignItems: "flex-start" }}>
                  <div style={{ flex: 1, width: "100%" }}>
                    <strong>Model Groq</strong>
                    <p className="muted" style={{ marginTop: 6 }}>
                      Cheie API:{" "}
                      {llm.groq_api_key_set ? (
                        <span style={{ color: "var(--ok, #1a7f4c)" }}>
                          setată ({llm.groq_api_key_hint})
                        </span>
                      ) : (
                        <span style={{ color: "var(--danger, #b00020)" }}>
                          lipsește — adaugă GROQ_API_KEY în .env și repornește API
                        </span>
                      )}
                    </p>
                    <label className="muted" style={{ display: "block", marginTop: 10 }}>
                      Model
                      <select
                        value={llm.groq_model}
                        disabled={llmBusy}
                        style={{ display: "block", width: "100%", marginTop: 6 }}
                        onChange={(e) => {
                          const model = e.target.value;
                          setLlm({ ...llm, groq_model: model });
                          void saveLlm({ groq_model: model });
                        }}
                      >
                        {(llm.available_groq_models || [llm.groq_model]).map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                      Endpoint: {llm.groq_base_url || "https://api.groq.com/openai/v1"}
                    </p>
                  </div>
                </div>

                <div className="admin-row" style={{ alignItems: "flex-start" }}>
                  <div style={{ flex: 1, width: "100%" }}>
                    <strong>Model local (Ollama)</strong>
                    <label className="muted" style={{ display: "block", marginTop: 10 }}>
                      Nume model
                      <input
                        value={llm.local_model}
                        disabled={llmBusy}
                        style={{ display: "block", width: "100%", marginTop: 6 }}
                        onChange={(e) =>
                          setLlm({ ...llm, local_model: e.target.value })
                        }
                        onBlur={() => {
                          if (llm.local_model?.trim()) {
                            void saveLlm({ local_model: llm.local_model.trim() });
                          }
                        }}
                      />
                    </label>
                    <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                      Ollama: {llm.ollama_base_url || "http://localhost:11434"}
                    </p>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
