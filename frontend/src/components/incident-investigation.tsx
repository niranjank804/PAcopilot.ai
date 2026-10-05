"use client";

import { RefreshCw, Search, Undo2, Wrench } from "lucide-react";
import Link from "next/link";

import { EnvironmentBadge } from "@/components/environment-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { changeHref, when, type Investigation, type Suspect } from "@/lib/team";

function Mitigation({ suspect, connectionId }: { suspect: Suspect; connectionId: string }) {
  const { mitigation } = suspect;

  if (mitigation.action === "rollback" && mitigation.change_id) {
    return (
      <Link
        href={changeHref(connectionId, mitigation.change_id)}
        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        <Undo2 className="h-3 w-3" aria-hidden />
        {mitigation.label} — opens the change; a person with rights rolls it back
      </Link>
    );
  }
  if (mitigation.action === "diagnose") {
    return (
      <Link href="/chat" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
        <Wrench className="h-3 w-3" aria-hidden />
        {mitigation.label} — ask the Troubleshooter: “Diagnose {mitigation.process}”
      </Link>
    );
  }
  if (mitigation.change_id) {
    return (
      <Link href={changeHref(connectionId, mitigation.change_id)} className="text-xs font-medium text-primary hover:underline">
        {mitigation.label}
      </Link>
    );
  }
  if (mitigation.alert_id) {
    return (
      <Link href="/alerts" className="text-xs font-medium text-primary hover:underline">
        {mitigation.label}
      </Link>
    );
  }
  return <span className="text-xs text-muted-foreground">{mitigation.label}</span>;
}

/**
 * The latest look at an incident's server: what is affected, the suspects
 * ranked with their evidence, and what to do about each. Nothing here acts
 * by itself — every mitigation opens a governed change or a diagnosis.
 */
export function IncidentInvestigation({
  investigations,
  connectionId,
  investigating,
  onInvestigate,
}: {
  investigations: Investigation[] | null | undefined;
  connectionId: string;
  investigating: boolean;
  onInvestigate: () => void;
}) {
  if (investigations === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Investigation</CardTitle>
          <CardDescription>
            Hidden: you cannot use this TM1 server, and the findings name its changes and processes.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const latest = investigations?.[0];
  const findings = latest?.findings;
  const previous = investigations?.[1]?.findings;
  const cleared = previous
    ? previous.suspects.filter((p) => !findings?.suspects.some((s) => s.title === p.title))
    : [];

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" aria-hidden />
            Investigation
          </CardTitle>
          <CardDescription>
            {latest
              ? `Last looked ${when(latest.created_at)} over the previous ${latest.window_hours} h. It only reads.`
              : "Not investigated yet."}
          </CardDescription>
        </div>
        <Button size="sm" variant="outline" onClick={onInvestigate} disabled={investigating}>
          <RefreshCw className={investigating ? "mr-1 h-3.5 w-3.5 animate-spin" : "mr-1 h-3.5 w-3.5"} />
          Investigate again
        </Button>
      </CardHeader>
      {findings ? (
        <CardContent className="space-y-4 text-sm">
          <p className="flex flex-wrap items-center gap-2 font-medium">
            <EnvironmentBadge environment={findings.environment} />
            {findings.summary}
          </p>

          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
            <dt className="text-muted-foreground">Affected</dt>
            <dd>{findings.affected.cubes.join(", ") || "—"}</dd>
            <dt className="text-muted-foreground">Written by</dt>
            <dd>
              {Object.entries(findings.affected.writers)
                .filter(([, ws]) => ws.length)
                .map(([cube, ws]) => `${cube}: ${ws.join(", ")}`)
                .join(" · ") || "—"}
            </dd>
            <dt className="text-muted-foreground">Rules read</dt>
            <dd>{findings.affected.rule_sources.join(", ") || "—"}</dd>
          </dl>

          {findings.suspects.length ? (
            <ol className="space-y-3" aria-label="Suspects, most likely first">
              {findings.suspects.map((s, index) => (
                <li key={`${s.title}-${index}`} className="rounded-md border p-3">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    <Badge variant={index === 0 ? "destructive" : "outline"}>{index === 0 ? "most likely" : `#${index + 1}`}</Badge>
                    {s.title}
                  </p>
                  {s.detail ? <p className="mt-1 text-xs text-muted-foreground">{s.detail}</p> : null}
                  {s.at ? <p className="text-xs text-muted-foreground">{when(s.at)}</p> : null}
                  <div className="mt-1.5">
                    <Mitigation suspect={s} connectionId={connectionId} />
                  </div>
                </li>
              ))}
            </ol>
          ) : null}

          {cleared.length ? (
            <div>
              <p className="text-xs font-medium">Cleared since the previous look</p>
              <ul className="list-disc pl-5 text-xs text-muted-foreground">
                {cleared.map((c) => (
                  <li key={c.title}>{c.title}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {findings.notes.length ? (
            <ul className="list-disc pl-5 text-xs text-muted-foreground">
              {findings.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          <p className="text-xs text-muted-foreground">{findings.applied_nothing}</p>
        </CardContent>
      ) : null}
    </Card>
  );
}
