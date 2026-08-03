import type { EventFeature, GridCell } from "@/lib/api";
import type { MessageKey } from "@/lib/locales/en";

/** HeatmapLayer aggregates into a texture and cannot report which cell is
 *  under the cursor, so an invisible pickable layer carries the tooltip.
 *  MapView matches on this id so no other layer can claim it. */
export const CELL_PICK_LAYER_ID = "convergence-cells";

/** Raw GDELT/ACLED points; shares the same getTooltip dispatcher. */
export const RAW_EVENT_LAYER_ID = "raw-events";

export interface PickInfo {
  layer?: { id: string } | null;
  object?: GridCell | EventFeature | null;
}

function hostOf(url: string | null): string | null {
  if (!url) return null;
  try { return new URL(url).hostname; } catch { return null; }
}

export function mapTooltip(
  info: PickInfo,
  t: (key: MessageKey) => string,
): { text: string } | null {
  if (!info.object) return null;

  if (info.layer?.id === CELL_PICK_LAYER_ID) {
    const c = info.object as GridCell;
    return {
      text: [
        `${t("cell.convergence")}: ${Math.round(c.convergence_score)}`,
        `${t("cell.alertLevel")}: ${c.alert_level}`,
        `${t("cell.events")}: ${c.total_events}`,
      ].join("\n"),
    };
  }

  if (info.layer?.id === RAW_EVENT_LAYER_ID) {
    const p = (info.object as EventFeature).properties;
    // Titles come from GKG headlines and can be absent; the host is the only
    // field guaranteed to say something useful.
    const head = p.title || hostOf(p.url) || `#${p.event_id}`;
    return { text: [head, p.event_date?.slice(0, 10) ?? ""].filter(Boolean).join("\n") };
  }

  return null;
}

/** @deprecated kept so existing imports/tests keep resolving. */
export const gridCellTooltip = mapTooltip;
