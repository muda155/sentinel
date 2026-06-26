// LLM verification threshold — mirrors SENTINEL_LLM_THRESHOLD (default 40).
// The backend enqueues a hotspot for SITREP generation when conf_score > threshold
// (strictly greater; see candidate_hotspots in pipeline/llm_verifier.py).
export const LLM_THRESHOLD = 40;

export type SitrepState = "ready" | "pending" | "below_threshold";

// Decide why a hotspot's detail panel has (or lacks) a SITREP.
// "below_threshold" means it will never be generated at the current conf_score;
// "pending" means it qualifies and is awaiting / undergoing LLM verification.
export function sitrepState(summaryText: string, confScore: number): SitrepState {
  if (summaryText.trim()) return "ready";
  return confScore > LLM_THRESHOLD ? "pending" : "below_threshold";
}
