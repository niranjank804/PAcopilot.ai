import { cn } from "@/lib/utils";

interface CellValue {
  coordinates: string[];
  value: number | string | null;
}

function shown(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : value;
}

function same(a: CellValue["value"] | undefined, b: CellValue["value"] | undefined): boolean {
  if (typeof a === "number" || typeof b === "number") return Number(a ?? 0) === Number(b ?? 0);
  return (a ?? "") === (b ?? "");
}

/**
 * A cell write, cell by cell: where, what it holds now, what it would hold.
 * "Now" is read from the server when the change is opened; the values are
 * read again and saved at the moment it is applied.
 */
export function CellWriteTable({
  current,
  proposed,
  reason,
}: {
  current: CellValue[] | undefined;
  proposed: CellValue[];
  reason?: string | null;
}) {
  return (
    <div className="space-y-2">
      {reason ? <p className="text-sm">Reason: {reason}</p> : null}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <caption className="sr-only">Cells to write, with current and new values</caption>
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Cell</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Now</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">New</th>
            </tr>
          </thead>
          <tbody>
            {proposed.map((cell, index) => {
              const now = current?.[index]?.value;
              const changes = !same(now, cell.value);
              return (
                <tr key={cell.coordinates.join("\u0000")} className="border-t">
                  <td className="px-3 py-1.5">{cell.coordinates.join(" · ")}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {current ? shown(now) : "?"}
                  </td>
                  <td className={cn("px-3 py-1.5 text-right tabular-nums", changes && "font-semibold")}>
                    {shown(cell.value)}
                    {!changes && current ? <span className="sr-only"> (unchanged)</span> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
