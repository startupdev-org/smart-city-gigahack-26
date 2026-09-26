"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Markdown, annexLabel } from "@/components/Markdown";
import { useAuth } from "@/components/AuthProvider";
import {
  apiChatMessages,
  apiChatStream,
  apiCreateChat,
  apiDeleteChat,
  apiFeedback,
  apiListChats,
  ChatResponse,
  ChatSession,
  ToolEvent,
} from "@/lib/api";

type ToolStep = ToolEvent & { id: string };

type Msg = {
  role: "user" | "assistant";
  text: string;
  data?: ChatResponse;
  status?: {
    step: string;
    label_ro: string;
    label_ru: string;
    label_en?: string;
  } | null;
  tools?: ToolStep[];
  streaming?: boolean;
  typing?: boolean;
};

type Source = ChatResponse["sources"][0] & {
  source_type?: string | null;
  year?: number | null;
};

const DISLIKE_REASONS = [
  { id: "wrong_source", ro: "Surse greșite / irelevante", ru: "Неверные источники", en: "Wrong / irrelevant sources" },
  { id: "incorrect", ro: "Răspuns incorect", ru: "Неверный ответ", en: "Incorrect answer" },
  { id: "incomplete", ro: "Incomplet", ru: "Неполно", en: "Incomplete" },
  { id: "outdated", ro: "Informație învechită", ru: "Устаревшая информация", en: "Outdated information" },
  { id: "didnt_answer", ro: "Nu a răspuns la întrebare", ru: "Не ответил на вопрос", en: "Didn't answer the question" },
  { id: "other", ro: "Altceva", ru: "Другое", en: "Something else" },
];

const SUGGESTIONS_RO = [
  "Ce autorizații îmi trebuie pentru construcție?",
  "Există concursuri publice deschise acum?",
  "Unde depun o petiție la Pretura Buiucani?",
];

const SUGGESTIONS_RU = [
  "Какие разрешения нужны для строительства?",
  "Есть ли открытые конкурсы сейчас?",
  "Куда подать петицию в претуру?",
];

const SUGGESTIONS_EN = [
  "What permits do I need for construction?",
  "Are there open public job contests right now?",
  "Where do I submit a petition at Pretura Buiucani?",
];

type UiLang = "ro" | "ru" | "en";

function tx(lang: UiLang, ro: string, ru: string, en: string) {
  if (lang === "ru") return ru;
  if (lang === "en") return en;
  return ro;
}

function toolLabel(t: { label_ro: string; label_ru: string; label_en?: string }, lang: UiLang) {
  if (lang === "ru") return t.label_ru;
  if (lang === "en") return t.label_en || t.label_ro;
  return t.label_ro;
}

const LIKES_KEY = "civicai_likes_v1";

function loadLikes(): Record<string, true> {
  try {
    return JSON.parse(localStorage.getItem(LIKES_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveLike(key: string) {
  const all = loadLikes();
  all[key] = true;
  localStorage.setItem(LIKES_KEY, JSON.stringify(all));
}

function likeKey(question: string, answer: string) {
  return `${(question || "").slice(0, 120)}::${(answer || "").slice(0, 160)}`;
}

function uniqueSources(sources: Source[]): Source[] {
  const seen = new Set<string>();
  const out: Source[] = [];
  for (const s of sources || []) {
    const key = (s.url || s.document || "").trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(s);
    if (out.length >= 4) break;
  }
  return out;
}

export function ChatApp() {
  const { user, logout, ready } = useAuth();
  const router = useRouter();
  const [lang, setLang] = useState<UiLang>(() => {
    if (typeof window === "undefined") return "ro";
    const saved = localStorage.getItem("civicai_lang");
    return saved === "ru" || saved === "en" || saved === "ro" ? saved : "ro";
  });
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [hoverSrc, setHoverSrc] = useState<string | null>(null);
  const [annexOpen, setAnnexOpen] = useState<Source | null>(null);
  const [dislikeFor, setDislikeFor] = useState<number | null>(null);
  const [dislikeReason, setDislikeReason] = useState("wrong_source");
  const [dislikeDetail, setDislikeDetail] = useState("");
  const [likes, setLikes] = useState<Record<string, true>>({});
  const [likePulse, setLikePulse] = useState<string | null>(null);
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLikes(loadLikes());
  }, []);

  useEffect(() => {
    localStorage.setItem("civicai_lang", lang);
  }, [lang]);

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    void refreshSessions(user.access_token);
  }, [ready, user, router]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function refreshSessions(token: string) {
    try {
      setSessions(await apiListChats(token));
    } catch {
      /* ignore */
    }
  }

  function onLogout() {
    logout();
    router.replace("/login");
  }

  async function openSession(id: number) {
    if (!user) return;
    setSessionId(id);
    const rows = await apiChatMessages(user.access_token, id);
    setMessages(
      rows.map(
        (r: {
          role: string;
          content: string;
          status?: string;
          sources?: ChatResponse["sources"];
        }) => ({
          role: r.role as "user" | "assistant",
          text: r.content,
          data:
            r.role === "assistant"
              ? {
                  status: r.status || "supported",
                  answer: r.content,
                  sources: r.sources || [],
                  next_action: null,
                  confidence: "medium",
                  language: lang,
                }
              : undefined,
        })
      )
    );
  }

  async function newChat() {
    if (!user) return;
    const s = await apiCreateChat(user.access_token);
    setSessions((prev) => [s, ...prev]);
    setSessionId(s.id);
    setMessages([]);
  }

  async function ask(q: string) {
    const question = q.trim();
    if (!question || busy || !user) return;
    if (!user.approved && user.role !== "admin") return;

    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", text: question },
      {
        role: "assistant",
        text: "",
        streaming: true,
        typing: false,
        tools: [],
        status: {
          step: "analyze",
          label_ro: "Analizez întrebarea…",
          label_ru: "Анализирую вопрос…",
          label_en: "Analyzing question…",
        },
      },
    ]);
    setInput("");
    try {
      const data = await apiChatStream(
        question,
        {
          onStatus: (status) => {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              if (!last?.streaming || last.typing) return m;
              copy[copy.length - 1] = { ...last, status };
              return copy;
            });
          },
          onTool: (tool) => {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              if (!last?.streaming) return m;
              const tools = [...(last.tools || [])];
              if (tool.status === "start") {
                tools.push({ ...tool, id: `${tool.name}-${tools.length}` });
              } else {
                const idx = [...tools]
                  .reverse()
                  .findIndex((t) => t.name === tool.name && t.status === "start");
                if (idx >= 0) {
                  const real = tools.length - 1 - idx;
                  tools[real] = { ...tools[real], ...tool };
                } else {
                  tools.push({ ...tool, id: `${tool.name}-${tools.length}` });
                }
              }
              copy[copy.length - 1] = {
                ...last,
                tools,
                status: {
                  step: tool.name,
                  label_ro: tool.label_ro + (tool.status === "start" ? "…" : ""),
                  label_ru: tool.label_ru + (tool.status === "start" ? "…" : ""),
                  label_en:
                    (tool.label_en || tool.label_ro) +
                    (tool.status === "start" ? "…" : ""),
                },
              };
              return copy;
            });
          },
          onToken: (t) => {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              if (!last?.streaming) return m;
              copy[copy.length - 1] = {
                ...last,
                text: (last.text || "") + t,
                typing: true,
                status: null,
              };
              return copy;
            });
          },
        },
        { token: user.access_token, sessionId, uiLanguage: lang }
      );
      if (data.session_id) {
        setSessionId(data.session_id);
        void refreshSessions(user.access_token);
      }
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = {
          role: "assistant",
          text: data.answer || data.status,
          data,
          tools: last?.tools || [],
          streaming: false,
          typing: false,
          status: null,
        };
        return copy;
      });
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      if (/auth|401|403/i.test(detail)) {
        onLogout();
        return;
      }
      const friendly = tx(
        lang,
        "Nu am putut finaliza răspunsul. Încearcă din nou peste câteva secunde.",
        "Не удалось завершить ответ. Попробуйте снова через несколько секунд.",
        "Could not finish the answer. Please try again in a few seconds."
      );
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last?.streaming) {
          copy[copy.length - 1] = { role: "assistant", text: friendly, streaming: false };
        } else copy.push({ role: "assistant", text: friendly });
        return copy;
      });
    } finally {
      setBusy(false);
    }
  }

  async function submitDislike() {
    if (dislikeFor == null) return;
    const m = messages[dislikeFor];
    const q = messages[dislikeFor - 1]?.text;
    await apiFeedback({
      question: q,
      answer: m?.text || m?.data?.answer,
      useful: false,
      reason: dislikeReason,
      detail: dislikeDetail.trim() || undefined,
    });
    setDislikeFor(null);
    setDislikeDetail("");
    setDislikeReason("wrong_source");
  }

  const placeholder = useMemo(
    () =>
      tx(lang, "Scrie o întrebare…", "Напишите вопрос…", "Write a question…"),
    [lang]
  );
  const suggestions =
    lang === "ru" ? SUGGESTIONS_RU : lang === "en" ? SUGGESTIONS_EN : SUGGESTIONS_RO;
  const canChat = Boolean(user && (user.approved || user.role === "admin"));

  if (!ready || !user) {
    return <div className="boot-screen">CivicAI</div>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="side-brand">CIVICAI</div>
        <div className="side-top">
          <button type="button" className="new-chat" onClick={() => void newChat()}>
            + Chat nou
          </button>
        </div>
        <div className="session-list">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`session ${sessionId === s.id ? "active" : ""}`}
              onClick={() => void openSession(s.id)}
            >
              <span>{s.title}</span>
              <span
                className="del"
                role="button"
                tabIndex={0}
                aria-label="Șterge"
                onClick={(e) => {
                  e.stopPropagation();
                  void apiDeleteChat(user.access_token, s.id).then(() => {
                    setSessions((prev) => prev.filter((x) => x.id !== s.id));
                    if (sessionId === s.id) {
                      setSessionId(null);
                      setMessages([]);
                    }
                  });
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") e.currentTarget.click();
                }}
              >
                ×
              </span>
            </button>
          ))}
        </div>
        <div className="side-foot">
          <div className="user-line">{user.email}</div>
          {!user.approved && user.role !== "admin" && (
            <div className="pending-banner">
              Contul așteaptă confirmarea unui administrator.
            </div>
          )}
          <div className="side-actions">
            {user.role === "admin" && (
              <Link href="/admin">Administrare · LLM</Link>
            )}
            <button type="button" onClick={onLogout}>
              Ieșire
            </button>
          </div>
        </div>
      </aside>

      <main className="chat-main">
        <header className="chat-head">
          <div className="title">CivicAI</div>
          <div className="head-actions">
            <button
              type="button"
              className={lang === "ro" ? "chip on" : "chip"}
              onClick={() => setLang("ro")}
            >
              RO
            </button>
            <button
              type="button"
              className={lang === "ru" ? "chip on" : "chip"}
              onClick={() => setLang("ru")}
            >
              RU
            </button>
            <button
              type="button"
              className={lang === "en" ? "chip on" : "chip"}
              onClick={() => setLang("en")}
            >
              EN
            </button>
          </div>
        </header>

        <div className="messages">
          {!canChat ? (
            <div className="pending-card">
              <h2>{tx(lang, "Cont în așteptare", "Аккаунт ожидает", "Pending account")}</h2>
              <p>
                {tx(
                  lang,
                  "Un administrator trebuie să confirme accesul tău. Revino după ce ești aprobat.",
                  "Администратор должен подтвердить доступ. Вернитесь после одобрения.",
                  "An administrator must approve your access. Come back once you are approved."
                )}
              </p>
            </div>
          ) : messages.length === 0 ? (
            <div className="empty-hero">
              <span className="hero-badge">Chișinău</span>
              <h1>
                {tx(lang, "Cu ce te putem ajuta?", "Чем можем помочь?", "How can we help?")}
              </h1>
              <p className="lede">
                {tx(
                  lang,
                  "Întreabă despre autorizații, termene, anunțuri — răspunsuri din surse oficiale.",
                  "Спрашивайте о разрешениях, сроках, объявлениях — ответы из официальных источников.",
                  "Ask about permits, deadlines, notices — answers from official sources."
                )}
              </p>
              <div className="suggest-row">
                {suggestions.map((s) => (
                  <button key={s} type="button" className="suggest" onClick={() => void ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {canChat &&
            messages.map((m, i) => {
              const srcs = m.data ? uniqueSources(m.data.sources || []) : [];
              return (
                <div key={i} className={`msg ${m.role}`}>
                  <div className="msg-inner">
                    {(m.tools?.length || 0) > 0 && (
                      <ToolSteps
                        tools={m.tools!}
                        lang={lang}
                      />
                    )}
                    {m.streaming && m.status && !m.typing && !m.tools?.length && (
                      <div className="live">
                        <span className="spinner" />
                        {toolLabel(m.status, lang)}
                      </div>
                    )}
                    {(m.text || m.typing) && (
                      <div className="msg-text">
                        {m.role === "assistant" ? (
                          <Markdown text={m.text} sources={srcs} lang={lang} />
                        ) : (
                          m.text
                        )}
                        {m.typing && <span className="caret" />}
                      </div>
                    )}
                    {m.data && !m.streaming && (
                      <div className="meta">
                        <div className="meta-row">
                          <StatusBadge status={m.data.status} lang={lang} />
                          <ConfidenceBadge
                            level={m.data.confidence}
                            score={m.data.confidence_score}
                            lang={lang}
                          />
                          {m.data.latency_ms != null && (
                            <span className="latency" title="Latency">
                              {m.data.latency_ms} ms
                            </span>
                          )}
                        </div>

                        {m.data.conflicts && m.data.conflicts.length > 0 && (
                          <div className="conflict-radar">
                            <div className="conflict-title">
                              {tx(
                                lang,
                                "Conflict radar — termene diferite",
                                "Радар конфликтов — разные сроки",
                                "Conflict radar — different deadlines"
                              )}
                            </div>
                            {m.data.conflicts.map((c, ci) => (
                              <div key={ci} className="conflict-grid">
                                <div className="conflict-pane">
                                  <div className="conflict-days">
                                    {c.left.days.join(" / ")}{" "}
                                    {tx(lang, "zile", "дней", "days")}
                                  </div>
                                  <div className="conflict-doc">{c.left.document}</div>
                                  <div className="conflict-quote">{c.left.quote}</div>
                                  {c.left.url && (
                                    <a href={c.left.url} target="_blank" rel="noreferrer">
                                      {tx(lang, "Deschide", "Открыть", "Open")}
                                    </a>
                                  )}
                                </div>
                                <div className="conflict-pane">
                                  <div className="conflict-days">
                                    {c.right.days.join(" / ")}{" "}
                                    {tx(lang, "zile", "дней", "days")}
                                  </div>
                                  <div className="conflict-doc">{c.right.document}</div>
                                  <div className="conflict-quote">{c.right.quote}</div>
                                  {c.right.url && (
                                    <a href={c.right.url} target="_blank" rel="noreferrer">
                                      {tx(lang, "Deschide", "Открыть", "Open")}
                                    </a>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {srcs.length > 0 && (
                          <div className="sources" role="list" aria-label="Anexe">
                            {srcs.map((s, j) => {
                              const hid = `${i}-${j}`;
                              return (
                                <div
                                  key={hid}
                                  className="source-wrap"
                                  role="listitem"
                                  onMouseEnter={() => setHoverSrc(hid)}
                                  onMouseLeave={() => setHoverSrc(null)}
                                >
                                  <button
                                    type="button"
                                    className="source cite-tag"
                                    onClick={() => setAnnexOpen(s)}
                                    aria-label={`${annexLabel(j + 1, s, lang)} ${s.document || ""}`}
                                  >
                                    {annexLabel(j + 1, s, lang)}
                                    {s.source_type && (
                                      <span className="type-pill">{s.source_type}</span>
                                    )}
                                    <span className="label">
                                      {shortLabel(s.document || s.url || "")}
                                    </span>
                                    {s.page != null && (
                                      <span className="page-pill">p.{s.page}</span>
                                    )}
                                  </button>
                                  {hoverSrc === hid && s.quote && (
                                    <div className="source-preview">{s.quote}</div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}

                        {m.data.next_action?.url && (
                          <a
                            className="contact-cta"
                            href={m.data.next_action.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span>
                              {tx(
                                lang,
                                "Mergi la contact / serviciu",
                                "К контакту / услуге",
                                "Go to contact / service"
                              )}
                            </span>
                            <strong>{m.data.next_action.label}</strong>
                            {m.data.next_action.contact && (
                              <em>{m.data.next_action.contact}</em>
                            )}
                          </a>
                        )}

                        <div className="fb">
                          {(() => {
                            const lk = likeKey(messages[i - 1]?.text || "", m.text);
                            const liked = Boolean(likes[lk]);
                            return (
                              <button
                                type="button"
                                title="Util"
                                className={`like-btn ${liked ? "liked" : ""} ${likePulse === lk ? "pulse" : ""}`}
                                onClick={() => {
                                  saveLike(lk);
                                  setLikes((prev) => ({ ...prev, [lk]: true }));
                                  setLikePulse(lk);
                                  setTimeout(() => setLikePulse(null), 600);
                                  void apiFeedback({
                                    question: messages[i - 1]?.text,
                                    answer: m.text,
                                    useful: true,
                                    reason: "correct",
                                  });
                                }}
                              >
                                👍
                              </button>
                            );
                          })()}
                          <button type="button" title="Nu e util" onClick={() => setDislikeFor(i)}>
                            👎
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          <div ref={messagesEnd} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              canChat
                ? placeholder
                : tx(
                    lang,
                    "Așteaptă aprobarea contului…",
                    "Ожидайте одобрения…",
                    "Waiting for account approval…"
                  )
            }
            disabled={busy || !canChat}
          />
          <button type="submit" disabled={busy || !canChat || !input.trim()}>
            {tx(lang, "Trimite", "Отправить", "Send")}
          </button>
        </form>
      </main>

      {annexOpen && (
        <div className="modal-backdrop" onClick={() => setAnnexOpen(null)}>
          <div
            className="modal annex-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={tx(lang, "Anexă", "Приложение", "Annex")}
          >
            <h3>{annexOpen.document}</h3>
            <p className="muted" style={{ margin: 0, fontSize: 13 }}>
              {annexOpen.source_type || "document"}
              {annexOpen.page != null ? ` · p.${annexOpen.page}` : ""}
              {annexOpen.year ? ` · ${annexOpen.year}` : ""}
            </p>
            <blockquote className="annex-quote">{annexOpen.quote}</blockquote>
            <div className="actions">
              {annexOpen.url && (
                <a
                  className="btn-primary"
                  href={annexOpen.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    textDecoration: "none",
                  }}
                >
                  {tx(lang, "Deschide sursa", "Открыть источник", "Open source")}
                </a>
              )}
              <button type="button" className="btn-ghost" onClick={() => setAnnexOpen(null)}>
                {tx(lang, "Închide", "Закрыть", "Close")}
              </button>
            </div>
          </div>
        </div>
      )}

      {dislikeFor != null && (
        <div className="modal-backdrop" onClick={() => setDislikeFor(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{tx(lang, "Ce nu a mers bine?", "Что пошло не так?", "What went wrong?")}</h3>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>
              Feedback-ul ajută echipa să îmbunătățească răspunsurile.
            </p>
            <div className="row">
              <label className="muted">Motiv</label>
              <select
                value={dislikeReason}
                onChange={(e) => setDislikeReason(e.target.value)}
              >
                {DISLIKE_REASONS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {tx(lang, r.ro, r.ru, r.en)}
                  </option>
                ))}
              </select>
            </div>
            <div className="row">
              <label className="muted">Detalii (opțional)</label>
              <textarea
                rows={4}
                value={dislikeDetail}
                onChange={(e) => setDislikeDetail(e.target.value)}
                placeholder={tx(
                  lang,
                  "Descrie pe scurt problema…",
                  "Кратко опишите проблему…",
                  "Briefly describe the issue…"
                )}
              />
            </div>
            <div className="actions">
              <button type="button" className="btn-ghost" onClick={() => setDislikeFor(null)}>
                {tx(lang, "Anulează", "Отмена", "Cancel")}
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void submitDislike()}
              >
                {tx(lang, "Trimite feedback", "Отправить отзыв", "Send feedback")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConfidenceBadge({
  level,
  score,
  lang,
}: {
  level?: string;
  score?: number;
  lang: UiLang;
}) {
  const pct = score != null ? Math.round(score * 100) : null;
  const label =
    level === "high"
      ? tx(lang, "Încredere mare", "Высокая уверенность", "High confidence")
      : level === "low"
        ? tx(lang, "Încredere scăzută", "Низкая уверенность", "Low confidence")
        : tx(lang, "Încredere medie", "Средняя уверенность", "Medium confidence");
  return (
    <span className={`badge conf ${level || "medium"}`}>
      {label}
      {pct != null ? ` · ${pct}%` : ""}
    </span>
  );
}

function ToolSteps({
  tools,
  lang,
}: {
  tools: ToolStep[];
  lang: UiLang;
}) {
  const [open, setOpen] = useState(false);
  const current =
    tools.find((t) => t.status === "start") ||
    tools[tools.length - 1] ||
    null;
  const doneCount = tools.filter((t) => t.status === "done").length;

  return (
    <div className="tool-timeline" aria-live="polite">
      <div className="tool-head">
        <div className="tool-title">
          {tx(lang, "Pași agent", "Шаги агента", "Agent steps")}
          <span className="tool-count">
            {doneCount}/{tools.length}
          </span>
        </div>
        <button
          type="button"
          className={`tool-toggle ${open ? "open" : ""}`}
          aria-expanded={open}
          title={tx(lang, "Arată toți pașii", "Показать все шаги", "Show all steps")}
          onClick={() => setOpen((v) => !v)}
        >
          <span aria-hidden>{open ? "▲" : "▼"}</span>
        </button>
      </div>

      {!open && current && (
        <div
          className={`tool-row current ${current.status}${current.optional ? " optional" : ""}`}
          title={current.detail || current.name}
        >
          <span className="tool-ico" aria-hidden>
            {current.status === "start"
              ? "…"
              : current.status === "error"
                ? "!"
                : "✓"}
          </span>
          <span className="tool-label">
            {toolLabel(current, lang)}
            {current.optional ? (
              <span className="tool-opt"> · {tx(lang, "opțional", "опц.", "opt.")}</span>
            ) : null}
          </span>
          {current.detail && current.status !== "start" && (
            <span className="tool-detail">{current.detail}</span>
          )}
          {typeof current.ms === "number" && current.status === "done" && (
            <span className="tool-ms">{current.ms}ms</span>
          )}
        </div>
      )}

      {open &&
        tools.map((t) => (
          <div
            key={t.id}
            className={`tool-row ${t.status}${t.optional ? " optional" : ""}`}
            title={t.detail || t.name}
          >
            <span className="tool-ico" aria-hidden>
              {t.status === "start" ? "…" : t.status === "error" ? "!" : "✓"}
            </span>
            <span className="tool-label">
              {toolLabel(t, lang)}
              {t.optional ? (
                <span className="tool-opt"> · {tx(lang, "opțional", "опц.", "opt.")}</span>
              ) : null}
            </span>
            {t.detail && t.status !== "start" && (
              <span className="tool-detail">{t.detail}</span>
            )}
            {typeof t.ms === "number" && t.status === "done" && (
              <span className="tool-ms">{t.ms}ms</span>
            )}
          </div>
        ))}
    </div>
  );
}

function shortLabel(s: string): string {
  const t = s.replace(/^https?:\/\//, "").replace(/\/$/, "");
  return t.length > 36 ? `${t.slice(0, 34)}…` : t;
}

function StatusBadge({
  status,
  lang,
}: {
  status: string;
  lang: UiLang;
}) {
  if (status === "supported") {
    return (
      <span className="badge">
        {tx(lang, "Verificat în corpus", "Проверено", "Verified in corpus")}
      </span>
    );
  }
  if (status === "conflict") {
    return (
      <span className="badge danger">
        {tx(lang, "Informații contradictorii", "Противоречие", "Conflicting information")}
      </span>
    );
  }
  return (
    <span className="badge warn">
      {tx(lang, "Nu am găsit în corpus", "Нет в корпусе", "Not found in corpus")}
    </span>
  );
}
