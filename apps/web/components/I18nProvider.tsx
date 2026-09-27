"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import i18n, { type Locale } from "@/lib/i18n";

export type { Locale } from "@/lib/i18n";

/* Legacy inline messages were moved to locales/{en,ro,ru}.json. */

type I18nValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, values?: Record<string, string | number>) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

function interpolate(message: string, values?: Record<string, string | number>) {
  if (!values) return message;
  return message.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? `{${name}}`));
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ro");

  useEffect(() => {
    const saved = window.localStorage.getItem("civicai_lang");
    if (saved === "ro" || saved === "ru" || saved === "en") {
      void i18n.changeLanguage(saved);
      setLocaleState(saved);
    }
    return i18n.onLanguageChange(() => setLocaleState(i18n.language));
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    window.localStorage.setItem("civicai_lang", locale);
  }, [locale]);

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale: (nextLocale) => i18n.changeLanguage(nextLocale),
      t: (key, values) => i18n.t(key, values),
    }),
    [locale]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}

export const LanguageProvider = I18nProvider;

export function useLanguage() {
  const { locale, setLocale } = useI18n();
  return { language: locale, setLanguage: setLocale, isLoading: false };
}

export function useTranslation() {
  const { t, setLocale } = useI18n();
  return { t, i18n: { changeLanguage: setLocale } };
}

export function LanguageSwitcher({ className = "chip" }: { className?: string }) {
  const { locale, setLocale } = useI18n();
  return (
    <div className="lang-row" aria-label="Language">
      {(["ro", "ru", "en"] as Locale[]).map((code) => (
        <button
          key={code}
          type="button"
          className={locale === code ? `${className} on` : className}
          onClick={() => void setLocale(code)}
          aria-pressed={locale === code}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
