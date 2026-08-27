import type { Claim, Translation } from "@/lib/api";

/** FR-30: English is canonical. These helpers only choose what to DISPLAY;
 *  every fallback path lands on the English source text, because an English
 *  panel is correct and an empty one is not. */

export function shouldTranslate(
  locale: string,
  summary: string | undefined,
  claims: Claim[] | undefined,
): boolean {
  if (locale !== "vi") return false;
  return Boolean(summary?.trim()) || (claims?.length ?? 0) > 0;
}

export function displaySummary(
  english: string,
  translation: Translation | null,
  showOriginal: boolean,
): string {
  if (showOriginal || !translation || !translation.summary_translated) return english;
  return translation.summary || english;
}

export function displayClaimText(
  claim: Claim,
  translation: Translation | null,
  showOriginal: boolean,
): string {
  if (showOriginal || !translation) return claim.claim_text;
  const hit = translation.claims.find((c) => c.claim_id === claim.claim_id);
  return hit?.text || claim.claim_text;
}
