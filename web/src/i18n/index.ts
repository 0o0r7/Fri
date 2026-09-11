import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fa from "./locales/fa.json";
import es from "./locales/es.json";
import ar from "./locales/ar.json";
import zh from "./locales/zh.json";
import fr from "./locales/fr.json";

export const SUPPORTED_LOCALES = [
  { code: "en", label: "English", flag: "🇬🇧", dir: "ltr" as const },
  { code: "fa", label: "فارسی", flag: "🇮🇷", dir: "rtl" as const },
  { code: "es", label: "Español", flag: "🇪🇸", dir: "ltr" as const },
  { code: "ar", label: "العربية", flag: "🇸🇦", dir: "rtl" as const },
  { code: "zh", label: "中文", flag: "🇨🇳", dir: "ltr" as const },
  { code: "fr", label: "Français", flag: "🇫🇷", dir: "ltr" as const },
];

export function isRTL(code: string): boolean {
  return SUPPORTED_LOCALES.find((l) => l.code === code)?.dir === "rtl";
}

const saved = typeof localStorage !== "undefined" ? localStorage.getItem("fri-lang") : null;
const initialLang = saved || (typeof navigator !== "undefined" ? navigator.language.split("-")[0] : "en");

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    fa: { translation: fa },
    es: { translation: es },
    ar: { translation: ar },
    zh: { translation: zh },
    fr: { translation: fr },
  },
  lng: SUPPORTED_LOCALES.some((l) => l.code === initialLang) ? initialLang : "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function applyDirection(code: string) {
  if (typeof document === "undefined") return;
  document.documentElement.dir = isRTL(code) ? "rtl" : "ltr";
  document.documentElement.lang = code;
}

if (typeof document !== "undefined") {
  applyDirection(i18n.language);
}

export default i18n;
