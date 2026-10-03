import { Badge } from "@/components/ui/badge";

export type Severity = "critical" | "high" | "medium" | "low";

export interface ImpactItem {
  object_type: string;
  name: string;
  severity?: Severity;
  reason?: string;
  depth?: number;
  relationship_type?: string;
}

export type ImpactEntry = ImpactItem | { note: string };

const ORDER: Severity[] = ["critical", "high", "medium", "low"];

const VARIANT: Record<Severity, "destructive" | "warning" | "secondary" | "outline"> = {
  critical: "destructive",
  high: "warning",
  medium: "secondary",
  low: "outline",
};

const LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

function isNote(entry: ImpactEntry): entry is { note: string } {
  return "note" in entry;
}

/** Whether approving a change with this impact must confirm it was read.
 * Mirrors needs_acknowledgement in backend/src/tm1/impact/analyzer.py. */
export function needsAcknowledgement(entries: ImpactEntry[] | null | undefined): boolean {
  return (entries ?? []).some(
    (e) => !isNote(e) && (e.severity === "critical" || e.severity === "high"),
  );
}

/**
 * What a change affects, counted by severity first and then listed with the
 * reason for each — "3 critical, 7 high" is what a reviewer reads before
 * anything else. Severity is always written out, never shown by colour alone.
 */
export function ImpactSummary({
  entries,
  maxItems = 40,
}: {
  entries: ImpactEntry[] | null | undefined;
  maxItems?: number;
}) {
  const all = entries ?? [];
  const notes = all.filter(isNote);
  const items = all.filter((e): e is ImpactItem => !isNote(e));
  const ranked = items.filter((i) => i.severity);
  const counts = Object.fromEntries(
    ORDER.map((s) => [s, ranked.filter((i) => i.severity === s).length]),
  ) as Record<Severity, number>;

  return (
    <div className="space-y-2 text-xs">
      {ranked.length ? (
        <div className="flex flex-wrap gap-1.5" aria-label="Impact by severity">
          {ORDER.map((severity) => (
            <Badge key={severity} variant={VARIANT[severity]}>
              {LABEL[severity]}: {counts[severity]}
            </Badge>
          ))}
        </div>
      ) : null}

      {items.length ? (
        <ul className="space-y-1">
          {[...items]
            .sort(
              (a, b) =>
                ORDER.indexOf(a.severity ?? "low") - ORDER.indexOf(b.severity ?? "low"),
            )
            .slice(0, maxItems)
            .map((item, index) => (
              <li key={`${item.object_type}:${item.name}:${index}`} className="flex gap-2">
                {item.severity ? (
                  <span className="w-16 shrink-0 font-medium">{LABEL[item.severity]}</span>
                ) : null}
                <span>
                  <span className="font-medium">
                    {item.object_type} {item.name}
                  </span>{" "}
                  <span className="text-muted-foreground">
                    {item.reason ?? item.relationship_type}
                  </span>
                </span>
              </li>
            ))}
          {items.length > maxItems ? (
            <li className="text-muted-foreground">and {items.length - maxItems} more</li>
          ) : null}
        </ul>
      ) : null}

      {notes.map((note) => (
        <p key={note.note} className="text-muted-foreground">
          {note.note}
        </p>
      ))}

      {!items.length && !notes.length ? (
        <p className="text-muted-foreground">Nothing in the dependency map depends on this.</p>
      ) : null}
    </div>
  );
}
