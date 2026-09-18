"use client";

import {
  BookOpen,
  CheckCircle2,
  Copy,
  GitPullRequestDraft,
  LineChart,
  Lock,
  Mic,
  Network,
  RotateCcw,
  ScrollText,
  Stethoscope,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A scripted replay of three real workflows, on a sample model.
 *
 * Deliberately not a video and not live data. Every tool name shown is one
 * the backend agents actually call (a test checks this against
 * backend/src/ai/tools), every agent is a real agent, and the change-draft
 * step behaves the way the product does: the AI drafts, a person executes.
 * The numbers are sample data and the section says so.
 */

type Step =
  | { kind: "user"; text: string; spoken?: boolean }
  | { kind: "tool"; tool: string; target: string }
  | { kind: "assistant"; text: string; code?: string }
  | { kind: "draft"; object: string; diff: string[] }
  | { kind: "chart"; mdx: string; bars: { label: string; value: number }[] };

export interface DemoScenario {
  key: string;
  label: string;
  icon: typeof Stethoscope;
  window: string;
  steps: Step[];
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    key: "diagnose",
    label: "Diagnose a rule",
    icon: Stethoscope,
    window: "Chat · troubleshooter agent",
    steps: [
      {
        kind: "user",
        text: "Gross Margin is right for every product but shows 0 at the EMEA total. Why?",
      },
      { kind: "tool", tool: "get_cube_rules", target: "Sales" },
      { kind: "tool", tool: "get_dimension", target: "Region" },
      {
        kind: "assistant",
        text: "The rule only calculates leaf cells, and the cube uses SKIPCHECK — but nothing feeds Gross Margin. TM1 skips unfed cells when it consolidates, so every total above product level reads 0. A feeder from Revenue fixes it.",
        code: "['Gross Margin'] = N: ['Revenue'] - ['COGS'];",
      },
    ],
  },
  {
    key: "draft",
    label: "Draft the fix",
    icon: Wrench,
    window: "Chat · developer agent",
    steps: [
      {
        kind: "user",
        text: "Add that feeder, following our coding standards.",
      },
      { kind: "tool", tool: "get_coding_standards", target: "Knowledge Base" },
      { kind: "tool", tool: "get_cube_rules", target: "Sales" },
      { kind: "tool", tool: "propose_rule_update", target: "Sales" },
      {
        kind: "draft",
        object: "Sales rules",
        diff: ["  FEEDERS;", "+ ['Revenue'] => ['Gross Margin'];"],
      },
      {
        kind: "assistant",
        text: "The feeder is drafted for review. Nothing has been written to TM1: someone with deploy rights has to execute it, and the current rules are snapshotted first so it can be rolled back.",
      },
    ],
  },
  {
    key: "chart",
    label: "Chart a question",
    icon: LineChart,
    window: "Visualize",
    steps: [
      { kind: "user", text: "Revenue by region for 2026, actuals." },
      { kind: "tool", tool: "execute_mdx", target: "Sales" },
      {
        kind: "chart",
        mdx: [
          "SELECT {[Period].[2026]} ON COLUMNS,",
          "  {[Region].[Americas], [Region].[EMEA], [Region].[APAC]} ON ROWS",
          "FROM [Sales]",
          "WHERE ([Measure].[Revenue], [Version].[Actual])",
        ].join("\n"),
        bars: [
          { label: "Americas", value: 48.2 },
          { label: "EMEA", value: 36.9 },
          { label: "APAC", value: 21.4 },
        ],
      },
      {
        kind: "assistant",
        text: "Americas leads on 2026 actual revenue, with EMEA about a quarter lower and APAC under half.",
      },
    ],
  },
  {
    key: "error",
    label: "Explain an error",
    icon: ScrollText,
    window: "Knowledge Base · Explain error",
    steps: [
      {
        kind: "user",
        text: "Error: TI process 'Load Sales' failed — CellPutN: Cube 'Sales' element 'Q5' not found in dimension 'Period'.",
      },
      {
        kind: "assistant",
        text: "The Data tab writes to a Period element that does not exist: the source file has a quarter 'Q5', almost certainly a total row. Skip rows whose Period is not a leaf before the CellPutN, or map 'Q5' to the year total in the Metadata tab.",
        code: "IF( DIMIX('Period', vPeriod) = 0 );\n  ItemSkip;\nENDIF;",
      },
    ],
  },
  {
    key: "dependencies",
    label: "Trace dependencies",
    icon: Network,
    window: "Chat · architect agent",
    steps: [
      { kind: "user", text: "What breaks if I rename the Region dimension?" },
      { kind: "tool", tool: "find_dependents", target: "Region" },
      {
        kind: "assistant",
        text: "Region is used by 4 cubes (Sales, Forecast, Headcount, Allocations), referenced in 2 rules and rebuilt by the process Update Region dimension. The Metadata Explorer shows the same graph interactively.",
      },
    ],
  },
  {
    key: "documents",
    label: "Ask your documents",
    icon: BookOpen,
    window: "Chat · developer agent",
    steps: [
      { kind: "user", text: "How do we name TI parameters?" },
      { kind: "tool", tool: "search_knowledge_base", target: "TI naming" },
      {
        kind: "assistant",
        text: "Your standard is a 'p' prefix in camel case — pSourceFile, pYear — with a String type unless the value is used in arithmetic. Source: TI Standards v3, section 2.1, in your Knowledge Base.",
      },
    ],
  },
  {
    key: "copy",
    label: "Copy a process",
    icon: Copy,
    window: "Chat · administrator agent",
    steps: [
      { kind: "user", text: "Create a copy of IT_Load Data." },
      { kind: "tool", tool: "get_process", target: "IT_Load Data" },
      { kind: "tool", tool: "propose_process_copy", target: "IT_Load Data - Copy" },
      {
        kind: "draft",
        object: "IT_Load Data - Copy",
        diff: ["  Datasource: ASCII Project.csv", "  6 variables, 15 lines of Data code", "+ new process, exact copy"],
      },
      {
        kind: "assistant",
        text: "An exact copy is drafted, read from the server rather than retyped. It is not in TM1 yet — someone with deploy rights executes it from Deployments.",
      },
    ],
  },
  {
    key: "voice",
    label: "Ask by voice",
    icon: Mic,
    window: "Chat · analyst agent · voice",
    steps: [
      { kind: "user", text: "Which cubes do we have?", spoken: true },
      { kind: "tool", tool: "list_cubes", target: "Sales model" },
      {
        kind: "assistant",
        text: "Twenty-four cubes. The largest are Sales, Forecast and Headcount; the rest are lookups and control cubes. Read back aloud, sentence by sentence, while the answer streams in.",
      },
    ],
  },
];

/** Pause between steps: long enough to read a tool row, short enough to watch. */
const STEP_DELAY_MS = 1100;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function ProductDemo() {
  const [active, setActive] = useState(0);
  // Everything is shown until the replay starts. That is what the server
  // renders, what a reader without JavaScript or with reduced motion keeps,
  // and it means the replay never has to guess whether it may animate.
  const [visible, setVisible] = useState(DEMO_SCENARIOS[0].steps.length);
  const [playing, setPlaying] = useState(false);
  const sectionRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const scenario = DEMO_SCENARIOS[active];

  const play = (index: number) => {
    setActive(index);

    if (prefersReducedMotion()) {
      setVisible(DEMO_SCENARIOS[index].steps.length);
      setPlaying(false);
      return;
    }

    setVisible(1);
    setPlaying(true);
  };

  // Start the first replay when the demo scrolls into view, once. Playing
  // it off screen would mean the visitor arrives at a finished transcript.
  useEffect(() => {
    const node = sectionRef.current;

    if (!node || prefersReducedMotion() || typeof IntersectionObserver === "undefined") {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          setVisible(1);
          setPlaying(true);
        }
      },
      { threshold: 0.3 },
    );

    observer.observe(node);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!playing) return;

    const timer = setTimeout(() => {
      if (visible >= scenario.steps.length) {
        setPlaying(false);
      } else {
        setVisible((count) => count + 1);
      }
    }, STEP_DELAY_MS);

    return () => clearTimeout(timer);
  }, [playing, visible, scenario.steps.length]);

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const offset =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;

    if (!offset) return;

    event.preventDefault();
    const next = (active + offset + DEMO_SCENARIOS.length) % DEMO_SCENARIOS.length;
    play(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <div ref={sectionRef} className="mx-auto max-w-4xl">
      <div
        role="tablist"
        aria-label="Demo scenarios"
        className="mb-4 flex flex-wrap justify-center gap-2"
      >
        {DEMO_SCENARIOS.map((item, index) => (
          <button
            key={item.key}
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`demo-tab-${item.key}`}
            aria-selected={index === active}
            aria-controls="demo-panel"
            tabIndex={index === active ? 0 : -1}
            onClick={() => play(index)}
            onKeyDown={onTabKeyDown}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              index === active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            <item.icon className="size-4" aria-hidden />
            {item.label}
          </button>
        ))}
      </div>

      <div
        id="demo-panel"
        role="tabpanel"
        aria-labelledby={`demo-tab-${scenario.key}`}
        className="overflow-hidden rounded-xl border border-border bg-card shadow-sm"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border/60 bg-muted/40 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex shrink-0 gap-1.5" aria-hidden>
              <span className="size-2.5 rounded-full bg-muted-foreground/30" />
              <span className="size-2.5 rounded-full bg-muted-foreground/30" />
              <span className="size-2.5 rounded-full bg-muted-foreground/30" />
            </div>
            <span className="truncate text-xs text-muted-foreground">
              PA-Copilot · {scenario.window}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => play(active)}
            disabled={playing}
            className="h-7 shrink-0 gap-1.5 text-xs"
          >
            <RotateCcw className="size-3.5" aria-hidden />
            Replay
          </Button>
        </div>

        {/* Fixed-height transcript: later steps are laid out from the start
            and only faded in, so the page never jumps as the replay runs. */}
        <ol className="space-y-3 p-4 sm:p-6" aria-live="polite">
          {scenario.steps.map((step, index) => {
            const shown = index < visible;

            return (
              <li
                key={`${scenario.key}-${index}`}
                aria-hidden={!shown}
                className={cn(
                  "motion-safe:transition-all motion-safe:duration-500",
                  shown ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
                )}
              >
                <DemoStep step={step} />
              </li>
            );
          })}
        </ol>
      </div>

      <p className="mt-3 text-center text-xs text-muted-foreground">
        Eight scripted replays on a sample Sales model — not live data or a
        customer environment. The agents and tool calls are the ones the
        product really uses; every draft shown waits for a person to
        deploy it.
      </p>
    </div>
  );
}

function DemoStep({ step }: { step: Step }) {
  switch (step.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <p className="flex max-w-[85%] items-start gap-2 rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
            {step.spoken ? (
              <Mic className="mt-0.5 size-3.5 shrink-0" aria-label="Spoken" />
            ) : null}
            <span>{step.text}</span>
          </p>
        </div>
      );

    case "tool":
      return (
        <div className="flex items-center gap-2 pl-1 text-xs text-muted-foreground">
          <CheckCircle2 className="size-3.5 shrink-0 text-primary" aria-hidden />
          <code className="font-mono text-foreground/80">{step.tool}</code>
          <span className="truncate">· {step.target}</span>
        </div>
      );

    case "assistant":
      return (
        <div className="max-w-[92%] space-y-2 rounded-2xl rounded-bl-sm bg-muted px-4 py-3 text-sm">
          {step.code ? (
            <pre className="overflow-x-auto rounded-md bg-background px-3 py-2 font-mono text-xs">
              {step.code}
            </pre>
          ) : null}
          <p>{step.text}</p>
        </div>
      );

    case "draft":
      return (
        <div className="max-w-[92%] rounded-lg border border-border bg-background">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
            <span className="flex items-center gap-2 text-sm font-medium">
              <GitPullRequestDraft className="size-4 text-primary" aria-hidden />
              Change draft · {step.object}
            </span>
            <Badge variant="secondary">Awaiting review</Badge>
          </div>
          <pre className="overflow-x-auto px-3 py-2 font-mono text-xs">
            {step.diff.map((line) => (
              <div
                key={line}
                className={cn(
                  line.startsWith("+") && "bg-primary/10 text-primary",
                )}
              >
                {line}
              </div>
            ))}
          </pre>
          <p className="flex items-center gap-2 border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
            <Lock className="size-3.5 shrink-0" aria-hidden />
            Only a person with deploy rights can execute this.
          </p>
        </div>
      );

    case "chart": {
      const max = Math.max(...step.bars.map((bar) => bar.value));

      return (
        <div className="max-w-[92%] space-y-3 rounded-lg border border-border bg-background p-3">
          <pre className="overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs">
            {step.mdx}
          </pre>
          <div
            className="space-y-2"
            role="img"
            aria-label={`Bar chart, sample data: ${step.bars
              .map((bar) => `${bar.label} ${bar.value} million`)
              .join(", ")}`}
          >
            {step.bars.map((bar) => (
              <div key={bar.label} className="flex items-center gap-3 text-xs">
                <span className="w-16 shrink-0 text-muted-foreground">
                  {bar.label}
                </span>
                <div className="h-5 flex-1 rounded-sm bg-muted">
                  <div
                    className="h-full rounded-sm bg-primary"
                    style={{ width: `${(bar.value / max) * 100}%` }}
                  />
                </div>
                <span className="w-12 shrink-0 text-right tabular-nums">
                  {bar.value}m
                </span>
              </div>
            ))}
          </div>
        </div>
      );
    }
  }
}
