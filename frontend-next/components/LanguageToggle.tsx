"use client";
import { useT } from "@/lib/i18n";
import { buttonStyle, FONT } from "@/lib/theme";

export default function LanguageToggle() {
  const { locale, setLocale } = useT();
  return (
    <button
      onClick={() => setLocale(locale === "vi" ? "en" : "vi")}
      title={
        locale === "vi" ? "Switch to English" : "Chuyển sang tiếng Việt"
      }
      style={{ ...buttonStyle, padding: "4px 10px", fontSize: FONT.sm, marginLeft: 8 }}
    >
      {locale === "vi" ? "EN" : "VI"}
    </button>
  );
}
