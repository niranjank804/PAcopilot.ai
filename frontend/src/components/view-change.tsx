/**
 * A new public MDX view as the approver sees it: which cube, what it is
 * called, and the MDX it will hold. Nothing existing is changed by it, so
 * there is no "before" side; if a view of that name is on the server now
 * (it was created by this change, or by someone since), its MDX is shown
 * when it differs.
 */
export function ViewChange({
  cube,
  viewName,
  mdx,
  rationale,
  currentMdx,
}: {
  cube: string;
  viewName: string;
  mdx: string;
  rationale?: string | null;
  currentMdx?: string | null;
}) {
  const differs =
    currentMdx != null && currentMdx.split(/\s+/).join(" ").trim() !== mdx.split(/\s+/).join(" ").trim();

  return (
    <div className="space-y-2" data-tour="governance-view">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Cube</dt>
        <dd>{cube}</dd>
        <dt className="text-muted-foreground">View (public)</dt>
        <dd>{viewName}</dd>
      </dl>
      {rationale ? <p className="text-sm">Reason: {rationale}</p> : null}
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">MDX</p>
        <pre className="max-h-56 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
          <code>{mdx || "(empty)"}</code>
        </pre>
      </div>
      {differs ? (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            On the server now, with different MDX
          </p>
          <pre className="max-h-56 overflow-auto rounded-md bg-destructive/10 p-2 text-xs whitespace-pre-wrap">
            <code>{currentMdx || "(not an MDX view)"}</code>
          </pre>
        </div>
      ) : null}
    </div>
  );
}
