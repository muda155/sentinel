import type { MessageKey } from "@/lib/i18n-core";

type TFn = (k: MessageKey) => string;

export function buildSubtitle(
  events: { event_type_label: string }[],
  t: TFn,
): string {
  if (events.length === 0) return "";
  const labels = [...new Set(events.map((e) => e.event_type_label))]
    .map((key) => t(`eventType.${key}` as MessageKey));
  return `${labels.join(" + ")} — ${events.length} ${t("detail.events")}`;
}
