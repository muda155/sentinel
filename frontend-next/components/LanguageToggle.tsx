"use client";
import { useT } from "@/lib/i18n";

export default function LanguageToggle() {
  const { locale, setLocale } = useT();
  return (
    <button
      onClick={() => setLocale(locale === "vi" ? "en" : "vi")}
      title={
        locale === "vi" ? "Switch to English" : "Chuyển sang tiếng Việt"
      }
      style={{ marginLeft: 8 }}
    >
      {locale === "vi" ? "EN" : "VI"}
    </button>
  );
}
