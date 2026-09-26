export const API_URL = process.env.NEXT_PUBLIC_API_URL?.trim() || "";
const STREAM_URL =
  process.env.NEXT_PUBLIC_API_URL?.trim() || "http://127.0.0.1:8000";

function url(path: string) {
  return `${API_URL}${path}`;
}

export type AuthUser = {
  access_token: string;
  email: string;
  role: string;
  approved: boolean;
};

export type ChatResponse = {
  status: string;
  answer: string;
  sources: {
    document: string;
    page: number | null;
    section: string | null;
    quote: string;
    url: string | null;
    source_type?: string | null;
    year?: number | null;
  }[];
  next_action: { label: string; url: string; contact: string | null } | null;
  confidence: string;
  confidence_score?: number;
  language: string;
  evidence_preview?: ChatResponse["sources"];
  session_id?: number | null;
  conflicts?: {
    left: {
      document: string;
      days: number[];
      quote: string;
      url?: string | null;
      page?: string | null;
    };
    right: {
      document: string;
      days: number[];
      quote: string;
      url?: string | null;
      page?: string | null;
    };
  }[];
  tools_used?: string[];
  latency_ms?: number | null;
  corpus?: Record<string, unknown> | null;
};

export type ChatStatusEvent = {
  step: string;
  label_ro: string;
  label_ru: string;
  label_en?: string;
};

export type ToolEvent = {
  name: string;
  status: "start" | "done" | "error";
  label_ro: string;
  label_ru: string;
  label_en?: string;
  detail?: string;
  ms?: number;
  optional?: boolean;
};

export type ChatSession = {
  id: number;
  title: string;
  updated_at?: string | null;
};

const TOKEN_KEY = "civicai_token";
const USER_KEY = "civicai_user";
const COOKIE_TOKEN = "civicai_token";
const COOKIE_USER = "civicai_user";

function setCookie(name: string, value: string, maxAgeSec = 60 * 60 * 24 * 14) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAgeSec}; SameSite=Lax`;
}

function clearCookie(name: string) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function saveAuth(u: AuthUser) {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, u.access_token);
  localStorage.setItem(
    USER_KEY,
    JSON.stringify({ email: u.email, role: u.role, approved: u.approved })
  );
  setCookie(COOKIE_TOKEN, u.access_token);
  setCookie(
    COOKIE_USER,
    JSON.stringify({ email: u.email, role: u.role, approved: u.approved })
  );
}

export function clearAuth() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  clearCookie(COOKIE_TOKEN);
  clearCookie(COOKIE_USER);
}

export function loadAuth(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem(TOKEN_KEY);
  const raw = localStorage.getItem(USER_KEY);
  if (!token || !raw) return null;
  try {
    const u = JSON.parse(raw);
    return {
      access_token: token,
      email: u.email,
      role: u.role,
      approved: Boolean(u.approved),
    };
  } catch {
    return null;
  }
}

/** Sync cookie from localStorage (for users logged in before cookie auth). */
export function syncAuthCookie() {
  const u = loadAuth();
  if (u) saveAuth(u);
}

function authHeaders(token?: string): HeadersInit {
  const t = token || loadAuth()?.access_token;
  return t
    ? { Authorization: `Bearer ${t}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

export async function apiRegister(email: string, password: string) {
  const res = await fetch(url("/api/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<AuthUser>;
}

export async function apiLogin(email: string, password: string) {
  const res = await fetch(url("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("Login failed");
  return res.json() as Promise<AuthUser>;
}

export async function apiMe(token: string) {
  const res = await fetch(url("/api/auth/me"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("me failed");
  return res.json();
}

export async function apiListChats(token: string): Promise<ChatSession[]> {
  const res = await fetch(url("/api/chats"), { headers: authHeaders(token) });
  if (!res.ok) throw new Error("chats failed");
  return res.json();
}

export async function apiCreateChat(token: string, title = "Chat nou") {
  const res = await fetch(url("/api/chats"), {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error("create chat failed");
  return res.json() as Promise<ChatSession>;
}

export async function apiChatMessages(token: string, sessionId: number) {
  const res = await fetch(url(`/api/chats/${sessionId}/messages`), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("messages failed");
  return res.json();
}

export async function apiDeleteChat(token: string, sessionId: number) {
  await fetch(url(`/api/chats/${sessionId}`), {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export async function apiChatStream(
  question: string,
  handlers: {
    onStatus: (s: ChatStatusEvent) => void;
    onToken: (t: string) => void;
    onTool?: (t: ToolEvent) => void;
  },
  opts?: { token?: string; sessionId?: number | null; uiLanguage?: string }
): Promise<ChatResponse> {
  const res = await fetch(`${STREAM_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      ...authHeaders(opts?.token),
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      question,
      top_k: 12,
      session_id: opts?.sessionId || null,
      ui_language: opts?.uiLanguage || null,
    }),
  });
  if (res.status === 401 || res.status === 403) {
    const body = await res.text().catch(() => "");
    throw new Error(body || `Auth: ${res.status}`);
  }
  if (!res.ok || !res.body) {
    const body = await res.text().catch(() => "");
    throw new Error(`Chat failed: ${res.status} ${body.slice(0, 200)}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ChatResponse | null = null;
  let eventName = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() || "";
    for (const line of parts) {
      const trimmed = line.replace(/\r$/, "");
      if (!trimmed) {
        eventName = "message";
        continue;
      }
      if (trimmed.startsWith("event:")) {
        eventName = trimmed.slice(6).trim();
        continue;
      }
      if (!trimmed.startsWith("data:")) continue;
      try {
        const data = JSON.parse(trimmed.slice(5).trim());
        if (eventName === "status") handlers.onStatus(data);
        if (eventName === "tool") handlers.onTool?.(data);
        if (eventName === "token" && typeof data.t === "string")
          handlers.onToken(data.t);
        if (eventName === "result") result = data;
      } catch {
        /* ignore */
      }
    }
  }
  if (!result) throw new Error("Chat stream ended without result");
  return result;
}

export async function apiAdminHealth(token: string) {
  const res = await fetch(url("/api/admin/health"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("health failed");
  return res.json();
}

export async function apiAdminDemoQuestions(token: string) {
  const res = await fetch(url("/api/admin/demo-questions"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("demo failed");
  return res.json();
}

export type LlmSettings = {
  provider: "local" | "groq";
  groq_model: string;
  local_model: string;
  groq_configured: boolean;
  groq_api_key_set: boolean;
  groq_api_key_hint?: string;
  groq_base_url?: string;
  ollama_base_url?: string;
  available_groq_models?: string[];
  ok?: boolean;
  error?: string;
};

export async function apiAdminLlmSettings(token: string): Promise<LlmSettings> {
  const res = await fetch(url("/api/admin/llm-settings"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("llm settings failed");
  return res.json();
}

export async function apiAdminPatchLlmSettings(
  token: string,
  body: { provider?: "local" | "groq"; groq_model?: string; local_model?: string }
): Promise<LlmSettings> {
  const res = await fetch(url("/api/admin/llm-settings"), {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "Nu am putut salva setările LLM"
    );
  }
  return data;
}

export async function apiFeedback(payload: {
  question?: string;
  answer?: string;
  useful: boolean;
  reason?: string;
  detail?: string;
}) {
  await fetch(url("/api/feedback/public"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function apiAdminFeedback(token: string) {
  const res = await fetch(url("/api/admin/feedback"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("feedback failed");
  return res.json();
}

export async function apiAdminStats(token: string) {
  const res = await fetch(url("/api/admin/stats"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Admin stats failed");
  return res.json();
}

export async function apiAdminCost(token: string) {
  const res = await fetch(url("/api/admin/cost"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Cost failed");
  return res.json();
}

export async function apiAdminUsers(token: string) {
  const res = await fetch(url("/api/admin/users"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("users failed");
  return res.json();
}

export async function apiAdminPatchUser(
  token: string,
  id: number,
  body: { approved?: boolean; role?: string }
) {
  const res = await fetch(url(`/api/admin/users/${id}`), {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("patch user failed");
  return res.json();
}

export async function apiAdminDocuments(token: string, q?: string) {
  const qs = q ? `?q=${encodeURIComponent(q)}` : "";
  const res = await fetch(url(`/api/admin/documents${qs}`), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("docs failed");
  return res.json();
}

export async function apiAdminDeleteDocument(token: string, id: number) {
  await fetch(url(`/api/admin/documents/${id}`), {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export type StaffPermissions = {
  admin_panel: boolean;
  users: boolean;
  llm: boolean;
  cost: boolean;
  health: boolean;
  demo: boolean;
  feedback: boolean;
  stats: boolean;
  documents: boolean;
  sources: boolean;
  ingest: boolean;
};

export function permissionsForRole(role: string): StaffPermissions {
  const staff = role === "admin" || role === "manager";
  const admin = role === "admin";
  return {
    admin_panel: staff,
    users: admin,
    llm: admin,
    cost: admin,
    health: admin,
    demo: admin,
    feedback: staff,
    stats: staff,
    documents: staff,
    sources: staff,
    ingest: staff,
  };
}

export async function apiAdminSources(token: string) {
  const res = await fetch(url("/api/admin/sources"), {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("sources failed");
  return res.json();
}

export async function apiAdminCreateSource(
  token: string,
  body: {
    name: string;
    url: string;
    type?: string;
    category?: string;
    priority?: string;
    active?: boolean;
  }
) {
  const res = await fetch(url("/api/admin/sources"), {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : "Nu am putut crea sursa"
    );
  }
  return data;
}

export async function apiAdminIngestUrl(
  token: string,
  body: { url: string; title?: string; source_name?: string; category?: string }
) {
  const res = await fetch(url("/api/admin/ingest/url"), {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : "Ingest URL eșuat"
    );
  }
  return data;
}

export async function apiAdminIngestText(
  token: string,
  body: {
    title: string;
    text: string;
    url?: string;
    source_name?: string;
    category?: string;
  }
) {
  const res = await fetch(url("/api/admin/ingest/text"), {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : "Ingest text eșuat"
    );
  }
  return data;
}

export async function apiAdminCostProject(
  token: string,
  body: Record<string, unknown>
) {
  const res = await fetch(url("/api/admin/cost/project"), {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Cost project failed");
  return res.json();
}
