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

/** Whether any claim is actually on screen in Vietnamese. The endpoint falls
 *  back to the English source per claim (an over-budget claim is never sent),
 *  and that fallback is the identical string, so an unchanged text means
 *  nothing was translated and no disclosure is owed. */
export function anyClaimTranslated(
  claims: Claim[] | undefined,
  translation: Translation | null,
): boolean {
  if (!translation) return false;
  return (claims ?? []).some((c) => {
    const hit = translation.claims.find((t) => t.claim_id === c.claim_id);
    return Boolean(hit?.text) && hit!.text !== c.claim_text;
  });
}
