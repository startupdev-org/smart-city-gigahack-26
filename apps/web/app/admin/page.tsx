"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import {
  apiAdminCost,
  apiAdminCostProject,
  apiAdminCreateSource,
  apiAdminDeleteDocument,
  apiAdminDemoQuestions,
  apiAdminDocuments,
  apiAdminFeedback,
  apiAdminHealth,
  apiAdminIngestText,
  apiAdminIngestUrl,
  apiAdminLlmSettings,
  apiAdminPatchLlmSettings,
  apiAdminPatchUser,
  apiAdminSources,
  apiAdminStats,
  apiAdminUsers,
  apiLogin,
  permissionsForRole,
  type AuthUser,
  type LlmSettings,
  type StaffPermissions,
} from "@/lib/api";

type Tab =
  | "overview"
  | "ingest"
  | "sources"
  | "docs"
  | "feedback"
  | "users"
  | "cost"
  | "llm"
  | "tools"
  | "health"
  | "demo";

async function settled<T>(
  p: Promise<T>,
  fallback: T
): Promise<{ ok: boolean; value: T; err?: string }> {
  try {
    return { ok: true, value: await p };
  } catch (e) {
    return {
      ok: false,
      value: fallback,
      err: e instanceof Error ? e.message : String(e),
    };
  }
}

function money(n: unknown, suffix = "USD") {
  const v = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(v)) return "—";
  return `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${suffix === "USD" ? "" : suffix}`.trim();
}

export default function AdminPage() {
  const { user, ready, logout, login } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<any>(null);
  const [cost, setCost] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [demo, setDemo] = useState<{ count: number; items: any[] } | null>(null);
  const [llm, setLlm] = useState<LlmSettings | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [docs, setDocs] = useState<any[]>([]);
  const [sources, setSources] = useState<any[]>([]);
  const [feedback, setFeedback] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [adminEmail, setAdminEmail] = useState("admin@civic.ai");
  const [adminPass, setAdminPass] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);

  // ingest form
  const [ingestUrl, setIngestUrl] = useState("");
  const [ingestTitle, setIngestTitle] = useState("");
  const [ingestTextTitle, setIngestTextTitle] = useState("");
  const [ingestText, setIngestText] = useState("");
  const [ingestBusy, setIngestBusy] = useState(false);
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [docQuery, setDocQuery] = useState("");

  // cost form
  const [costForm, setCostForm] = useState({
    active_users: 200,
    requests_per_user_month: 28,
    avg_input_tokens: 1400,
    avg_output_tokens: 420,
    tool_calls_per_q: 1.3,
    llm_provider: "groq_gpt_oss_120b",
    embedding_provider: "local_bge_m3",
    rerank_provider: "local_bge",
    infra_fixed_usd: 55,
    electricity_usd: 28,
    storage_usd: 12,
    bandwidth_usd: 14,
    support_hours: 16,
    support_hourly_usd: 15,
    target_profit_usd: 450,
    margin_pct: 30 as string | number,
    fx_mdl: 17.85,
  });
  const [costBusy, setCostBusy] = useState(false);
  const [opexNotes, setOpexNotes] = useState<Record<string, string>>({});
  const [toolCatalog, setToolCatalog] = useState<any[]>([]);

  const perms: StaffPermissions = useMemo(
    () => permissionsForRole(user?.role || "citizen"),
    [user?.role]
  );

  const pending = useMemo(
    () =>
      users.filter(
        (u) => !u.approved && u.role !== "admin" && u.role !== "manager"
      ),
    [users]
  );

  const tabs = useMemo(() => {
    const all: { id: Tab; label: string; show: boolean }[] = [
      { id: "overview", label: "Overview", show: perms.stats },
      { id: "ingest", label: "Încarcă materiale", show: perms.ingest },
      { id: "sources", label: "Surse", show: perms.sources },
      { id: "docs", label: "Documente", show: perms.documents },
      { id: "feedback", label: "Feedback", show: perms.feedback },
      { id: "users", label: "Utilizatori & roluri", show: perms.users },
      { id: "cost", label: "Cost & profit", show: perms.cost },
      { id: "llm", label: "LLM", show: perms.llm },
      { id: "tools", label: "Agent tools", show: perms.llm || perms.stats },
      { id: "health", label: "Health", show: perms.health },
      { id: "demo", label: "Demo Q", show: perms.demo },
    ];
    return all.filter((t) => t.show);
  }, [perms]);

  async function refresh(t: string, role: string) {
    const p = permissionsForRole(role);
    const jobs: Promise<{ ok: boolean; value: any; err?: string }>[] = [];
    const map: string[] = [];

    if (p.stats) {
      map.push("stats");
      jobs.push(settled(apiAdminStats(t), null));
    }
    if (p.cost) {
      map.push("cost");
      jobs.push(settled(apiAdminCost(t), null));
    }
    if (p.users) {
      map.push("users");
      jobs.push(settled(apiAdminUsers(t), []));
    }
    if (p.documents) {
      map.push("docs");
      jobs.push(settled(apiAdminDocuments(t), []));
    }
    if (p.sources) {
      map.push("sources");
      jobs.push(settled(apiAdminSources(t), []));
    }
    if (p.feedback) {
      map.push("feedback");
      jobs.push(settled(apiAdminFeedback(t), []));
    }
    if (p.health) {
      map.push("health");
      jobs.push(settled(apiAdminHealth(t), null));
    }
    if (p.demo) {
      map.push("demo");
      jobs.push(settled(apiAdminDemoQuestions(t), null));
    }
    if (p.llm) {
      map.push("llm");
      jobs.push(settled(apiAdminLlmSettings(t), null));
    }
    // tools catalog is public
    map.push("tools");
    jobs.push(
      settled(
        fetch(
          `${(process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "")}/api/tools`
        ).then((r) => {
          if (!r.ok) throw new Error("tools");
          return r.json();
        }),
        null
      )
    );

    const results = await Promise.all(jobs);
    results.forEach((r, i) => {
      const k = map[i];
      if (k === "stats") setStats(r.value);
      if (k === "cost") {
        setCost(r.value);
        const inp = r.value?.inputs;
        const def = r.value?.catalog?.default_opex || {};
        const notes = r.value?.catalog?.opex_notes || {};
        setOpexNotes(notes);
        setCostForm((f) => ({
          ...f,
          active_users: inp?.active_users ?? def.active_users ?? f.active_users,
          requests_per_user_month:
            inp?.requests_per_user_month ??
            def.requests_per_user_month ??
            f.requests_per_user_month,
          llm_provider: inp?.llm_provider ?? f.llm_provider,
          target_profit_usd:
            inp?.target_profit_usd ?? def.target_profit_usd ?? f.target_profit_usd,
          margin_pct: inp?.margin_pct ?? def.margin_pct ?? f.margin_pct,
          infra_fixed_usd: def.infra_fixed_usd ?? f.infra_fixed_usd,
          electricity_usd: def.electricity_usd ?? f.electricity_usd,
          storage_usd: def.storage_usd ?? f.storage_usd,
          bandwidth_usd: def.bandwidth_usd ?? f.bandwidth_usd,
          support_hours: def.support_hours ?? f.support_hours,
          support_hourly_usd: def.support_hourly_usd ?? f.support_hourly_usd,
          fx_mdl: def.fx_mdl ?? f.fx_mdl,
        }));
      }
      if (k === "users") setUsers(r.value);
      if (k === "docs") setDocs(r.value);
      if (k === "sources") setSources(r.value);
      if (k === "feedback") setFeedback(r.value);
      if (k === "health") setHealth(r.value);
      if (k === "demo") setDemo(r.value);
      if (k === "llm") setLlm(r.value);
      if (k === "tools") setToolCatalog(r.value?.tools || []);
    });
    const errs = results.filter((r) => !r.ok).map((r) => r.err || "failed");
    setPartialErrors(errs);
    if (errs.length === results.length && results.length > 0) {
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
    if (!permissionsForRole(user.role).admin_panel) {
      setError(
        `Contul ${user.email} (${user.role}) nu are acces la panoul operațional.`
      );
      setLoaded(true);
      return;
    }
    const first = permissionsForRole(user.role);
    setTab(first.stats ? "overview" : first.feedback ? "feedback" : "ingest");
    void refresh(user.access_token, user.role)
      .then(() => setLoaded(true))
      .catch((e) => {
        setError(
          e instanceof Error
            ? e.message
            : "Nu am putut încărca panoul (token invalid sau API oprit)."
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
      if (!permissionsForRole(u.role).admin_panel) {
        setError(`Contul ${u.email} nu este admin/manager.`);
        return;
      }
      login(u);
      setLoaded(false);
      await refresh(u.access_token, u.role);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Autentificare eșuată");
    } finally {
      setLoginBusy(false);
    }
  }

  function flash(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(""), 2800);
  }

  async function approve(id: number, approved: boolean) {
    if (!user) return;
    setBusyId(id);
    try {
      await apiAdminPatchUser(user.access_token, id, { approved });
      await refresh(user.access_token, user.role);
      flash(approved ? "Utilizator aprobat" : "Acces revocat");
    } finally {
      setBusyId(null);
    }
  }

  async function setRole(id: number, role: string) {
    if (!user) return;
    setBusyId(id);
    try {
      await apiAdminPatchUser(user.access_token, id, { role });
      await refresh(user.access_token, user.role);
      flash(`Rol actualizat → ${role}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rol eșuat");
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
      flash(
        next.provider === "groq"
          ? `LLM: Groq · ${next.groq_model}`
          : `LLM: Local · ${next.local_model}`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Salvare LLM eșuată");
    } finally {
      setLlmBusy(false);
    }
  }

  async function runIngestUrl() {
    if (!user || !ingestUrl.trim()) return;
    setIngestBusy(true);
    setError("");
    try {
      const r = await apiAdminIngestUrl(user.access_token, {
        url: ingestUrl.trim(),
        title: ingestTitle.trim() || undefined,
      });
      flash(`Indexat: ${r.title} (${r.chunks} chunks)`);
      setIngestUrl("");
      setIngestTitle("");
      await refresh(user.access_token, user.role);
      setTab("docs");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest eșuat");
    } finally {
      setIngestBusy(false);
    }
  }

  async function runIngestText() {
    if (!user || !ingestTextTitle.trim() || ingestText.trim().length < 40) return;
    setIngestBusy(true);
    setError("");
    try {
      const r = await apiAdminIngestText(user.access_token, {
        title: ingestTextTitle.trim(),
        text: ingestText,
      });
      flash(`Material salvat: ${r.title} (${r.chunks} chunks)`);
      setIngestTextTitle("");
      setIngestText("");
      await refresh(user.access_token, user.role);
      setTab("docs");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest eșuat");
    } finally {
      setIngestBusy(false);
    }
  }

  async function addSource() {
    if (!user || !sourceName.trim() || !sourceUrl.trim()) return;
    setIngestBusy(true);
    try {
      await apiAdminCreateSource(user.access_token, {
        name: sourceName.trim(),
        url: sourceUrl.trim(),
        category: "manual",
        priority: "P1",
      });
      flash("Sursă adăugată");
      setSourceName("");
      setSourceUrl("");
      await refresh(user.access_token, user.role);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sursă eșuată");
    } finally {
      setIngestBusy(false);
    }
  }

  async function runCostProject() {
    if (!user) return;
    setCostBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { ...costForm };
      if (costForm.margin_pct === "" || costForm.margin_pct === null) {
        body.margin_pct = null;
      } else {
        body.margin_pct = Number(costForm.margin_pct);
      }
      const r = await apiAdminCostProject(user.access_token, body);
      setCost(r);
      flash("Proiecție cost recalculată");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Proiecție eșuată");
    } finally {
      setCostBusy(false);
    }
  }

  async function searchDocs() {
    if (!user) return;
    const list = await apiAdminDocuments(
      user.access_token,
      docQuery.trim() || undefined
    );
    setDocs(list);
  }

  if (!ready || !loaded) {
    return <div className="boot-screen">CivicAI</div>;
  }

  if (!user || !perms.admin_panel) {
    return (
      <div className="admin-shell">
        <div className="admin-wrap" style={{ maxWidth: 440 }}>
          <Link href="/" className="muted">
            ← Înapoi la chat
          </Link>
          <h1 className="admin-h1">Panou operațional</h1>
          {error && (
            <div className="err" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
          <p className="muted" style={{ marginTop: 12, lineHeight: 1.5 }}>
            Acces pentru <strong>admin</strong> sau <strong>manager</strong>.
            Manager: feedback, statistici, încărcare documente/surse.
          </p>
          <form
            onSubmit={doAdminLogin}
            style={{ marginTop: 16, display: "grid", gap: 10 }}
          >
            <label className="admin-field">
              Email
              <input
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                autoComplete="username"
              />
            </label>
            <label className="admin-field">
              Parolă
              <input
                type="password"
                value={adminPass}
                onChange={(e) => setAdminPass(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" className="btn" disabled={loginBusy}>
              {loginBusy ? "…" : "Intră în panou"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const token = user.access_token;
  const totals = (cost?.totals || {}) as Record<string, unknown>;
  const scenarios = (cost?.scenarios || []) as any[];
  const sensitivity = (cost?.sensitivity || []) as any[];
  const catalogLlm = (() => {
    const raw =
      (cost as any)?.provider_catalog?.llm || (cost as any)?.catalog?.llm;
    if (Array.isArray(raw)) return raw;
    if (raw && typeof raw === "object") {
      return Object.entries(raw).map(([id, v]: [string, any]) => ({
        id,
        label: v.label || id,
        in: v.input_per_m,
      }));
    }
    return [
      { id: "local_ollama", label: "Local Ollama", in: 0 },
      { id: "groq_gpt_oss_120b", label: "Groq gpt-oss-120b", in: 0.15 },
      { id: "openai_gpt4o_mini", label: "GPT-4o mini", in: 0.15 },
      { id: "anthropic_haiku", label: "Claude Haiku", in: 0.8 },
    ];
  })();

  return (
    <div className="admin-shell">
      <div className="admin-wrap admin-wrap-wide">
        <header className="admin-top">
          <div>
            <Link href="/" className="muted">
              ← Chat
            </Link>
            <h1 className="admin-h1">CivicAI Control</h1>
            <p className="admin-sub">
              {user.email} · rol <strong>{user.role}</strong>
              {user.role === "manager"
                ? " · feedback · stats · materiale"
                : " · acces complet"}
            </p>
          </div>
          <div className="admin-top-actions">
            <button
              type="button"
              className="btn-ghost"
              onClick={() =>
                void refresh(token, user.role).catch((e) => setError(String(e)))
              }
            >
              Reîncarcă
            </button>
            <button type="button" className="btn-ghost" onClick={() => logout()}>
              Logout
            </button>
          </div>
        </header>

        {error && <div className="err">{error}</div>}
        {partialErrors.length > 0 && (
          <div className="err" style={{ opacity: 0.8 }}>
            Unele endpoint-uri: {partialErrors.slice(0, 3).join("; ")}
          </div>
        )}
        {toast && <div className="toast">{toast}</div>}

        <nav className="admin-nav">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "admin-nav-item on" : "admin-nav-item"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.id === "users" && pending.length > 0
                ? ` (${pending.length})`
                : ""}
              {t.id === "feedback" && feedback.length
                ? ` (${feedback.length})`
                : ""}
            </button>
          ))}
        </nav>

        {tab === "overview" && stats && (
          <section className="admin-section">
            <h2>Overview</h2>
            <div className="admin-kpi-grid">
              {[
                ["Documente", stats.documents],
                ["Chunks", stats.chunks],
                ["Surse", stats.sources],
                ["Căutări", stats.searches],
                ["Utilizatori", stats.users_total],
                ["Aprobați", stats.users_approved],
                ["Feedback", stats.feedback_total],
                ["Util %", stats.feedback_useful_pct ?? "—"],
              ].map(([k, v]) => (
                <div key={String(k)} className="admin-kpi">
                  <div className="admin-kpi-label">{String(k)}</div>
                  <div className="admin-kpi-value">{String(v)}</div>
                </div>
              ))}
            </div>
            <p className="muted" style={{ marginTop: 12 }}>
              pgvector: {String(stats.pgvector)} · ultima crawl:{" "}
              {String(stats.last_crawl || "—")}
            </p>
          </section>
        )}

        {tab === "ingest" && (
          <section className="admin-section">
            <h2>Încarcă materiale</h2>
            <p className="muted">
              Adaugă un URL oficial (HTML/PDF/Office) sau lipește text — se
              chunk-uiește și se indexează în RAG.
            </p>
            <div className="admin-card">
              <h3>Din link</h3>
              <label className="admin-field">
                URL
                <input
                  value={ingestUrl}
                  onChange={(e) => setIngestUrl(e.target.value)}
                  placeholder="https://…"
                />
              </label>
              <label className="admin-field">
                Titlu (opțional)
                <input
                  value={ingestTitle}
                  onChange={(e) => setIngestTitle(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="btn"
                disabled={ingestBusy || !ingestUrl.trim()}
                onClick={() => void runIngestUrl()}
              >
                {ingestBusy ? "Indexez…" : "Descarcă & indexează"}
              </button>
            </div>
            <div className="admin-card" style={{ marginTop: 14 }}>
              <h3>Text / notă internă</h3>
              <label className="admin-field">
                Titlu
                <input
                  value={ingestTextTitle}
                  onChange={(e) => setIngestTextTitle(e.target.value)}
                />
              </label>
              <label className="admin-field">
                Conținut (≥40 caractere)
                <textarea
                  rows={8}
                  value={ingestText}
                  onChange={(e) => setIngestText(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="btn"
                disabled={
                  ingestBusy ||
                  !ingestTextTitle.trim() ||
                  ingestText.trim().length < 40
                }
                onClick={() => void runIngestText()}
              >
                Salvează în corpus
              </button>
            </div>
          </section>
        )}

        {tab === "sources" && (
          <section className="admin-section">
            <h2>Surse</h2>
            <div className="admin-card">
              <h3>Adaugă sursă</h3>
              <div className="admin-form-row">
                <label className="admin-field">
                  Nume
                  <input
                    value={sourceName}
                    onChange={(e) => setSourceName(e.target.value)}
                  />
                </label>
                <label className="admin-field">
                  URL rădăcină
                  <input
                    value={sourceUrl}
                    onChange={(e) => setSourceUrl(e.target.value)}
                    placeholder="https://…"
                  />
                </label>
              </div>
              <button
                type="button"
                className="btn"
                disabled={ingestBusy}
                onClick={() => void addSource()}
              >
                Adaugă sursă
              </button>
            </div>
            <div className="admin-table-wrap" style={{ marginTop: 16 }}>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Nume</th>
                    <th>Prioritate</th>
                    <th>Docs</th>
                    <th>URL</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <strong>{s.name}</strong>
                        <div className="muted">{s.code}</div>
                      </td>
                      <td>{s.priority}</td>
                      <td>{s.documents}</td>
                      <td>
                        <a href={s.url} target="_blank" rel="noreferrer">
                          {s.url}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "docs" && (
          <section className="admin-section">
            <h2>Documente indexate</h2>
            <div className="admin-form-row" style={{ marginBottom: 12 }}>
              <input
                value={docQuery}
                onChange={(e) => setDocQuery(e.target.value)}
                placeholder="Caută titlu / URL…"
                style={{ flex: 1 }}
              />
              <button type="button" className="btn" onClick={() => void searchDocs()}>
                Caută
              </button>
            </div>
            <div className="admin-list">
              {docs.map((d) => (
                <div key={d.id} className="admin-row">
                  <div>
                    <strong>{d.title}</strong>
                    <div className="muted">
                      {d.mime_type} ·{" "}
                      {d.url ? (
                        <a href={d.url} target="_blank" rel="noreferrer">
                          link
                        </a>
                      ) : (
                        "—"
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() =>
                      void apiAdminDeleteDocument(token, d.id).then(() =>
                        refresh(token, user.role)
                      )
                    }
                  >
                    Șterge
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        {tab === "feedback" && (
          <section className="admin-section">
            <h2>Feedback cetățeni</h2>
            <div className="admin-list">
              {feedback.length === 0 ? (
                <p className="muted">Niciun feedback încă.</p>
              ) : (
                feedback.map((f) => (
                  <div key={f.id} className="admin-row admin-row-stack">
                    <div>
                      <span
                        className={
                          f.useful ? "admin-badge ok" : "admin-badge bad"
                        }
                      >
                        {f.useful ? "util" : "nu"}
                      </span>{" "}
                      <span className="muted">{f.reason || "—"}</span>
                    </div>
                    <div>
                      <strong>Q:</strong> {f.question || "—"}
                    </div>
                    {f.detail && <div className="muted">{f.detail}</div>}
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        {tab === "users" && (
          <section className="admin-section">
            <h2>Utilizatori & roluri</h2>
            <p className="muted">
              Roluri: <code>citizen</code>, <code>employee</code>,{" "}
              <code>manager</code> (feedback + materiale + stats),{" "}
              <code>admin</code> (tot).
            </p>
            {pending.length > 0 && (
              <div className="admin-card warn" style={{ marginBottom: 14 }}>
                <h3>În așteptare ({pending.length})</h3>
                {pending.map((u) => (
                  <div key={u.id} className="admin-row">
                    <div>
                      <strong>{u.email}</strong>
                      <div className="muted">{u.role}</div>
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
                ))}
              </div>
            )}
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Rol</th>
                    <th>Status</th>
                    <th>Acțiuni</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td>{u.email}</td>
                      <td>
                        <select
                          value={u.role}
                          disabled={busyId === u.id}
                          onChange={(e) => void setRole(u.id, e.target.value)}
                        >
                          {["citizen", "employee", "manager", "admin"].map(
                            (r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            )
                          )}
                        </select>
                      </td>
                      <td>{u.approved ? "aprobat" : "pending"}</td>
                      <td>
                        {!u.approved && (
                          <button
                            type="button"
                            className="btn"
                            onClick={() => void approve(u.id, true)}
                          >
                            Aprobă
                          </button>
                        )}
                        {u.approved && u.role === "citizen" && (
                          <button
                            type="button"
                            className="btn-ghost"
                            onClick={() => void approve(u.id, false)}
                          >
                            Revocă
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "cost" && (
          <section className="admin-section">
            <h2>Cost, pricing & profit</h2>
            <p className="muted">
              Proiecții pe utilizatori × cereri/lună, tokeni reali pe provider
              (Groq, OpenAI, Anthropic, Google, DeepSeek, local), OPEX, preț
              sugerat / user și break-even.
            </p>

            <div className="admin-card">
              <h3>Cerere & utilizare</h3>
              <div className="admin-grid-3">
                {(
                  [
                    ["active_users", "Utilizatori activi"],
                    ["requests_per_user_month", "Cereri / user / lună"],
                    ["avg_input_tokens", "Tokeni input medii"],
                    ["avg_output_tokens", "Tokeni output medii"],
                    ["tool_calls_per_q", "Tool calls / întrebare"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="admin-field">
                    {label}
                    <input
                      type="number"
                      step="any"
                      value={(costForm as any)[key]}
                      onChange={(e) =>
                        setCostForm({
                          ...costForm,
                          [key]: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                ))}
                <label className="admin-field">
                  Provider LLM
                  <select
                    value={costForm.llm_provider}
                    onChange={(e) =>
                      setCostForm({ ...costForm, llm_provider: e.target.value })
                    }
                  >
                    {catalogLlm.map((p: any) => (
                      <option key={p.id || p} value={p.id || p}>
                        {p.label || p.id || p}
                        {p.in != null ? ` (in $${p.in}/M)` : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="admin-card" style={{ marginTop: 14 }}>
              <div className="admin-card-head">
                <h3>OPEX estimat (Chișinău · on-prem/hybrid)</h3>
                <span className="admin-pill">estimate CivicAI</span>
              </div>
              <p className="muted" style={{ marginTop: 0 }}>
                Valorile de mai jos sunt estimate pentru un PC RAG mereu pornit +
                ops part-time — nu placeholder-urile vechi 40/18/5.
              </p>
              <div className="admin-grid-3">
                {(
                  [
                    ["infra_fixed_usd", "Infra fixă USD"],
                    ["electricity_usd", "Electricitate USD"],
                    ["storage_usd", "Storage USD"],
                    ["bandwidth_usd", "Bandwidth USD"],
                    ["support_hours", "Ore support / lună"],
                    ["support_hourly_usd", "Tarif support USD/oră"],
                    ["fx_mdl", "Curs MDL / USD"],
                    ["target_profit_usd", "Profit țintă USD / lună"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="admin-field">
                    {label}
                    <input
                      type="number"
                      step="any"
                      value={(costForm as any)[key]}
                      onChange={(e) =>
                        setCostForm({
                          ...costForm,
                          [key]: Number(e.target.value),
                        })
                      }
                    />
                    {opexNotes[key] && (
                      <span className="admin-hint">{opexNotes[key]}</span>
                    )}
                  </label>
                ))}
                <label className="admin-field">
                  Marjă % (preferată; lasă gol pt. profit țintă)
                  <input
                    type="number"
                    value={costForm.margin_pct}
                    placeholder="30"
                    onChange={(e) =>
                      setCostForm({
                        ...costForm,
                        margin_pct: e.target.value,
                      })
                    }
                  />
                  {opexNotes.margin_pct && (
                    <span className="admin-hint">{opexNotes.margin_pct}</span>
                  )}
                </label>
              </div>
              <button
                type="button"
                className="btn"
                style={{ marginTop: 12 }}
                disabled={costBusy}
                onClick={() => void runCostProject()}
              >
                {costBusy ? "Calculez…" : "Recalculează proiecția"}
              </button>
            </div>

            {totals.total_cost_usd != null && (
              <div className="admin-kpi-grid" style={{ marginTop: 16 }}>
                {[
                  ["Cost total / lună", money(totals.total_cost_usd)],
                  ["Venit necesar", money(totals.revenue_needed_usd)],
                  ["Profit", money(totals.profit_usd)],
                  ["Preț / user / lună", money(totals.price_per_user_month_usd)],
                  ["Preț / cerere", money(totals.price_per_request_usd)],
                  ["Cost / cerere", money(totals.cost_per_request_usd)],
                  ["MDL venit", `${totals.revenue_needed_mdl} MDL`],
                  ["Break-even users", String(totals.break_even_users_approx)],
                ].map(([k, v]) => (
                  <div key={String(k)} className="admin-kpi">
                    <div className="admin-kpi-label">{k}</div>
                    <div className="admin-kpi-value">{v}</div>
                  </div>
                ))}
              </div>
            )}

            {cost?.recommendation != null && String(cost.recommendation) !== "" ? (
              <p className="admin-callout">{String(cost.recommendation)}</p>
            ) : null}

            {scenarios.length > 0 && (
              <div className="admin-table-wrap" style={{ marginTop: 16 }}>
                <h3>Comparație provideri (stack complet)</h3>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Provider</th>
                      <th>LLM USD</th>
                      <th>Stack USD</th>
                      <th>Stack MDL</th>
                      <th>$ / user</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scenarios.map((s) => (
                      <tr
                        key={s.provider_id}
                        className={
                          s.provider_id === costForm.llm_provider
                            ? "admin-row-hl"
                            : undefined
                        }
                      >
                        <td>{s.label}</td>
                        <td>{money(s.total_usd)}</td>
                        <td>{money(s.stack_total_usd)}</td>
                        <td>{s.stack_total_mdl}</td>
                        <td>{money(s.suggested_price_per_user_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {sensitivity.length > 0 && (
              <div className="admin-table-wrap" style={{ marginTop: 16 }}>
                <h3>Sensitivitate (users × cereri)</h3>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Users</th>
                      <th>Req/user</th>
                      <th>Questions</th>
                      <th>Cost total</th>
                      <th>Cost/user</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sensitivity.map((s, i) => (
                      <tr key={i}>
                        <td>{s.users}</td>
                        <td>{s.req_per_user}</td>
                        <td>{s.questions}</td>
                        <td>{money(s.total_cost_usd)}</td>
                        <td>{money(s.per_user_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {cost?.breakdown && (
              <div className="admin-card" style={{ marginTop: 16 }}>
                <h3>Breakdown OPEX</h3>
                <pre className="admin-pre">
                  {JSON.stringify(cost.breakdown, null, 2)}
                </pre>
                {cost.llm && (
                  <>
                    <h3>LLM detail</h3>
                    <pre className="admin-pre">
                      {JSON.stringify(cost.llm, null, 2)}
                    </pre>
                  </>
                )}
              </div>
            )}
          </section>
        )}

        {tab === "llm" && llm && (
          <section className="admin-section">
            <h2>LLM runtime</h2>
            <div className="admin-card">
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
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
                  onClick={() => void saveLlm({ provider: "groq" })}
                >
                  Groq Cloud
                </button>
              </div>
              <p className="muted" style={{ marginTop: 10 }}>
                Activ:{" "}
                <strong>
                  {llm.provider === "groq"
                    ? `Groq · ${llm.groq_model}`
                    : `Local · ${llm.local_model}`}
                </strong>
                {" · "}
                cheie:{" "}
                {llm.groq_api_key_set
                  ? `setată (${llm.groq_api_key_hint})`
                  : "lipsă"}
              </p>
              <label className="admin-field">
                Model Groq
                <select
                  value={llm.groq_model}
                  disabled={llmBusy}
                  onChange={(e) => {
                    setLlm({ ...llm, groq_model: e.target.value });
                    void saveLlm({ groq_model: e.target.value });
                  }}
                >
                  {(llm.available_groq_models || [llm.groq_model]).map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
              <label className="admin-field">
                Model local
                <input
                  value={llm.local_model}
                  disabled={llmBusy}
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
            </div>
          </section>
        )}

        {tab === "tools" && (
          <section className="admin-section">
            <h2>Agent tools</h2>
            <p className="muted">
              Pipeline-ul poate citi / actualiza documente, extrage termene,
              căuta fraze exacte, acoperire surse etc. Opționale rulează când
              contextul o cere.
            </p>
            <div className="admin-tool-grid">
              {toolCatalog.map((t) => (
                <div
                  key={t.name}
                  className={
                    t.optional ? "admin-tool-card optional" : "admin-tool-card"
                  }
                >
                  <div className="admin-tool-name">{t.name}</div>
                  <div className="admin-tool-label">
                    {t.label_ro || t.label_en}
                  </div>
                  <span className="admin-pill">
                    {t.optional ? "optional" : "core"}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {tab === "health" && health && (
          <section className="admin-section">
            <h2>Health</h2>
            <pre className="admin-pre">{JSON.stringify(health, null, 2)}</pre>
          </section>
        )}

        {tab === "demo" && demo && (
          <section className="admin-section">
            <h2>Demo questions ({demo.count})</h2>
            <pre className="admin-pre">
              {JSON.stringify(demo.items?.slice(0, 10), null, 2)}
            </pre>
          </section>
        )}
      </div>
    </div>
  );
}
