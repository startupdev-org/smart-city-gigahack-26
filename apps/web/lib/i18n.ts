import enTranslations from "@/locales/en.json";
import roTranslations from "@/locales/ro.json";
import ruTranslations from "@/locales/ru.json";

export type Locale = "ro" | "ru" | "en";
type TranslationTree = Record<string, unknown>;

class BasicI18n {
  private currentLanguage: Locale = "ro";
  private resources: Record<Locale, { translation: TranslationTree }> = {
    en: { translation: enTranslations },
    ro: { translation: roTranslations },
    ru: { translation: ruTranslations },
  };
  private listeners: Array<() => void> = [];

  get language() {
    return this.currentLanguage;
  }

  changeLanguage(language: Locale) {
    this.currentLanguage = language;
    this.listeners.forEach((listener) => listener());
    return Promise.resolve();
  }

  onLanguageChange(callback: () => void) {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((listener) => listener !== callback);
    };
  }

  t(key: string, values?: Record<string, string | number>) {
    let value: unknown = this.resources[this.currentLanguage].translation;
    for (const part of key.split(".")) {
      value = value && typeof value === "object" ? (value as TranslationTree)[part] : undefined;
    }
    if (typeof value !== "string") return key;
    return values
      ? value.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? `{${name}}`))
      : value;
  }
}

const i18n = new BasicI18n();
export default i18n;
