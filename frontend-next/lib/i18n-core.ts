import { en, type MessageKey } from "@/lib/locales/en";
import { vi } from "@/lib/locales/vi";

export type Locale = "vi" | "en";
export const DEFAULT_LOCALE: Locale = "vi";
export const STORAGE_KEY = "sentinel_locale";

const DICTS: Record<Locale, Record<MessageKey, string>> = { en, vi };

export function makeT(locale: Locale) {
  const dict = DICTS[locale];
  return (key: MessageKey): string => dict[key] ?? key;
}
export type { MessageKey };
