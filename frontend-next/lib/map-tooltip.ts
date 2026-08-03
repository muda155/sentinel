import type { GridCell } from "@/lib/api";
import type { MessageKey } from "@/lib/locales/en";

/** HeatmapLayer aggregates into a texture and cannot report which cell is
 *  under the cursor, so an invisible pickable layer carries the tooltip.
 *  MapView matches on this id so no other layer can claim it. */
export const CELL_PICK_LAYER_ID = "convergence-cells";

export interface PickInfo {
  layer?: { id: string } | null;
  object?: GridCell | null;
}

export function gridCellTooltip(
  info: PickInfo,
  t: (key: MessageKey) => string,
): { text: string } | null {
  if (!info.object || info.layer?.id !== CELL_PICK_LAYER_ID) return null;
  const c = info.object;
  return {
    text: [
      `${t("cell.convergence")}: ${Math.round(c.convergence_score)}`,
      `${t("cell.alertLevel")}: ${c.alert_level}`,
      `${t("cell.events")}: ${c.total_events}`,
    ].join("\n"),
  };
}
