"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { apiLogin, apiRegister } from "@/lib/api";

export default function LoginClient() {
  const { user, ready, login } = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [lang, setLang] = useState<"ro" | "ru">("ro");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace(next.startsWith("/") ? next : "/");
  }, [ready, user, router, next]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const u =
        mode === "login"
          ? await apiLogin(email, password)
          : await apiRegister(email, password);
      login(u);
      router.replace(next.startsWith("/") ? next : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Autentificare eșuată");
    } finally {
      setSubmitting(false);
    }
  }

  if (!ready || user) {
    return <div className="boot-screen">CivicAI</div>;
  }

  return (
    <main className="auth-shell">
      <div className="auth-card">
        <div className="brand-mark">CIVICAI</div>
        <h1 className="brand-lg">
          {mode === "login" ? "Autentificare" : "Cont nou"}
        </h1>
        <p className="lede">
          {lang === "ro"
            ? "Asistentul Primăriei Chișinău — răspunsuri clare din documente oficiale."
            : "Ассистент примэрии Кишинёва — ответы из официальных документов."}
        </p>
        <div className="auth-tabs">
          <button
            type="button"
            className={mode === "login" ? "on" : ""}
            onClick={() => setMode("login")}
          >
            Autentificare
          </button>
          <button
            type="button"
            className={mode === "register" ? "on" : ""}
            onClick={() => setMode("register")}
          >
            Cont nou
          </button>
        </div>
        <form onSubmit={onSubmit} className="auth-form">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            type="email"
            required
            autoComplete="email"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Parolă (min. 6 caractere)"
            type="password"
            minLength={6}
            required
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
          <button type="submit" disabled={submitting}>
            {submitting
              ? "…"
              : mode === "login"
                ? "Intră în cont"
                : "Creează cont"}
          </button>
          {error && <div className="err">{error}</div>}
        </form>
        <p className="hint">
          După înregistrare, un administrator confirmă contul — durează de obicei
          puțin.
        </p>
        <div className="lang-row">
          <button
            type="button"
            className={lang === "ro" ? "chip on" : "chip"}
            onClick={() => setLang("ro")}
          >
            Română
          </button>
          <button
            type="button"
            className={lang === "ru" ? "chip on" : "chip"}
            onClick={() => setLang("ru")}
          >
            Русский
          </button>
        </div>
      </div>
    </main>
  );
}
