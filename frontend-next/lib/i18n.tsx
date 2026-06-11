"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { DEFAULT_LOCALE, STORAGE_KEY, makeT, type Locale, type MessageKey } from "@/lib/i18n-core";

type Ctx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (k: MessageKey) => string;
};
const LocaleContext = createContext<Ctx>({
  locale: DEFAULT_LOCALE,
  setLocale: () => {},
  t: makeT(DEFAULT_LOCALE),
});

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "vi") setLocaleState(saved);
  }, []);
  const setLocale = (l: Locale) => {
    setLocaleState(l);
    window.localStorage.setItem(STORAGE_KEY, l);
  };
  return (
    <LocaleContext.Provider value={{ locale, setLocale, t: makeT(locale) }}>
      {children}
    </LocaleContext.Provider>
  );
}

export const useT = () => useContext(LocaleContext);
