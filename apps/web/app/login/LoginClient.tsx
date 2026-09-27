"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { LanguageSwitcher, useI18n } from "@/components/I18nProvider";
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
  const { t } = useI18n();
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
      setError(err instanceof Error ? err.message : t("auth.authenticationFailed"));
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
        <div className="brand-mark">CivicAI</div>
        <h1 className="brand-lg">
          {mode === "login" ? t("auth.welcomeBack") : t("auth.newAccount")}
        </h1>
        <p className="lede">
          {t("auth.description")}
        </p>
        <div className="auth-tabs">
          <button
            type="button"
            className={mode === "login" ? "on" : ""}
            onClick={() => setMode("login")}
          >
            {t("auth.signIn")}
          </button>
          <button
            type="button"
            className={mode === "register" ? "on" : ""}
            onClick={() => setMode("register")}
          >
            {t("auth.newAccount")}
          </button>
        </div>
        <form onSubmit={onSubmit} className="auth-form">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("auth.email")}
            type="email"
            required
            autoComplete="email"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t("auth.passwordHint")}
            type="password"
            minLength={6}
            required
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
          <button type="submit" disabled={submitting}>
            {submitting
              ? "…"
              : mode === "login"
                ? t("auth.enterAccount")
                : t("auth.createYourAccount")}
          </button>
          {error && <div className="err">{error}</div>}
        </form>
        <p className="hint">
          {t("auth.approvalHint")}
        </p>
        <LanguageSwitcher />
      </div>
    </main>
  );
}
