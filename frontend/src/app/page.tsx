import {
  AudioLines,
  FileText,
  GitBranch,
  Image as ImageIcon,
  KeyRound,
  LineChart,
  Lock,
  MessageSquare,
  ScrollText,
  Shield,
  ShieldCheck,
  Sigma,
  Sparkles,
  Terminal,
  UserCheck,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const FEATURES = [
  {
    icon: Terminal,
    title: "TI Script Assistant",
    description:
      "Generate, refactor, and debug TurboIntegrator processes with AI that understands your cube model.",
  },
  {
    icon: Sigma,
    title: "Rules & Feeders Intelligence",
    description:
      "Explain and validate rule and feeder logic in plain language before it ever touches production.",
  },
  {
    icon: LineChart,
    title: "Visualize",
    description:
      "Ask a question in plain English, get an MDX query and a live, styled chart back — no manual query writing.",
  },
  {
    icon: ScrollText,
    title: "Explain Error",
    description:
      "Paste a TM1 error and get a clear explanation of what went wrong and how to fix it.",
  },
  {
    icon: MessageSquare,
    title: "Multimodal Chat",
    description:
      "Attach PDFs, screenshots, and Word docs directly in chat — the AI reads and reasons over them natively.",
  },
  {
    icon: AudioLines,
    title: "Voice Input",
    description:
      "Speak your question instead of typing it — dictation built directly into the chat composer.",
  },
  {
    icon: ShieldCheck,
    title: "Human-Gated Writes",
    description:
      "The AI drafts rule and process changes; a permitted human reviews and executes them from the same thread.",
  },
  {
    icon: FileText,
    title: "Knowledge Base",
    description:
      "Ground answers in your own uploaded documentation, retrieved automatically as context.",
  },
];

const WORKFLOW = [
  {
    step: "01",
    title: "Ask",
    description: "Describe what you need in plain language, in chat.",
  },
  {
    step: "02",
    title: "AI Drafts",
    description: "The right agent proposes a rule, process, or query change.",
  },
  {
    step: "03",
    title: "Human Reviews",
    description: "A permitted reviewer sees the exact diff and confirms it inline.",
  },
  {
    step: "04",
    title: "Verified & Audited",
    description:
      "Changes are snapshotted before write, verified after, and auto-restored on failure.",
  },
];

const SECURITY = [
  {
    icon: Shield,
    title: "Role-based access",
    description:
      "Super Admin, Organization Admin, Planner, Analyst, and Viewer roles gate exactly what each person can see and do.",
  },
  {
    icon: UserCheck,
    title: "Admin-approved access",
    description:
      "New users request access and an administrator approves before they can sign in — access can be revoked just as easily.",
  },
  {
    icon: Lock,
    title: "No unattended writes",
    description:
      "AI agents can only draft changes. Executing or rolling back a change always requires an explicit human action.",
  },
  {
    icon: KeyRound,
    title: "Google Sign-In",
    description:
      "Sign in with an existing Google account tied to an approved PA-Copilot user — no new password to manage.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2 font-semibold tracking-tight">
            <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Sparkles className="size-4" />
            </div>
            PA <span className="text-primary">Copilot</span>
          </div>
          <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
            <a href="#platform" className="hover:text-foreground">
              Platform
            </a>
            <a href="#workflow" className="hover:text-foreground">
              Workflow
            </a>
            <a href="#security" className="hover:text-foreground">
              Security
            </a>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
            >
              Sign in
            </Link>
            <Link
              href="/request-access"
              className={cn(buttonVariants({ variant: "default", size: "sm" }))}
            >
              Sign up
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <section className="mx-auto max-w-6xl px-6 pt-20 pb-16 text-center">
          <Badge variant="secondary" className="mb-6">
            Now in beta testing
          </Badge>
          <h1 className="mx-auto max-w-3xl text-4xl font-bold tracking-tight text-balance sm:text-5xl">
            An AI engineering copilot for{" "}
            <span className="text-primary">IBM Planning Analytics</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground text-balance">
            Write and debug TI scripts, explain rules and errors, chart data from a
            question, and safely draft TM1 changes — with a human always in control
            of what actually gets written.
          </p>
          <div className="mt-8 flex items-center justify-center gap-3">
            <Link
              href="/request-access"
              className={cn(buttonVariants({ variant: "default", size: "lg" }), "px-6")}
            >
              Sign up
            </Link>
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: "outline", size: "lg" }), "px-6")}
            >
              Sign in
            </Link>
          </div>
        </section>

        <section id="platform" className="border-t border-border/60 bg-muted/30 py-20">
          <div className="mx-auto max-w-6xl px-6">
            <div className="mx-auto mb-12 max-w-2xl text-center">
              <h2 className="text-3xl font-bold tracking-tight">
                Built for TM1 developers and admins
              </h2>
              <p className="mt-3 text-muted-foreground">
                Every feature is scoped to real TM1 workflows — nothing generic
                bolted on.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {FEATURES.map((feature) => (
                <Card key={feature.title}>
                  <CardHeader>
                    <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <feature.icon className="size-4.5" />
                    </div>
                    <CardTitle>{feature.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground">
                      {feature.description}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        <section id="workflow" className="py-20">
          <div className="mx-auto max-w-6xl px-6">
            <div className="mx-auto mb-12 max-w-2xl text-center">
              <h2 className="text-3xl font-bold tracking-tight">
                Every write goes through a human
              </h2>
              <p className="mt-3 text-muted-foreground">
                The AI proposes changes. It never executes them on its own.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {WORKFLOW.map((item) => (
                <div
                  key={item.step}
                  className="rounded-xl border border-border/60 bg-card p-5"
                >
                  <div className="text-2xl font-bold text-primary/30">
                    {item.step}
                  </div>
                  <h3 className="mt-1 font-semibold">{item.title}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="security" className="border-t border-border/60 bg-muted/30 py-20">
          <div className="mx-auto max-w-6xl px-6">
            <div className="mx-auto mb-12 max-w-2xl text-center">
              <h2 className="text-3xl font-bold tracking-tight">
                Security and governance, by default
              </h2>
              <p className="mt-3 text-muted-foreground">
                Access control and audit trails aren&apos;t an add-on — they&apos;re
                how the platform works.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {SECURITY.map((item) => (
                <div
                  key={item.title}
                  className="flex gap-4 rounded-xl border border-border/60 bg-card p-5"
                >
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <item.icon className="size-5" />
                  </div>
                  <div>
                    <h3 className="font-semibold">{item.title}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {item.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="py-20">
          <div className="mx-auto max-w-3xl px-6 text-center">
            <div className="mb-4 flex justify-center gap-2 text-muted-foreground">
              <GitBranch className="size-5" />
              <ImageIcon className="size-5" />
            </div>
            <h2 className="text-3xl font-bold tracking-tight">
              Ready to try it on your environment?
            </h2>
            <p className="mt-3 text-muted-foreground">
              Sign up and you&apos;re in — no approval wait during the beta.
            </p>
            <div className="mt-8 flex items-center justify-center gap-3">
              <Link
                href="/request-access"
                className={cn(
                  buttonVariants({ variant: "default", size: "lg" }),
                  "px-6",
                )}
              >
                Sign up
              </Link>
              <Link
                href="/login"
                className={cn(buttonVariants({ variant: "outline", size: "lg" }), "px-6")}
              >
                Sign in
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border/60 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-6 text-sm text-muted-foreground sm:flex-row">
          <p>&copy; {new Date().getFullYear()} PA-Copilot. All rights reserved.</p>
          <div className="flex items-center gap-4">
            <Link href="/login" className="hover:text-foreground">
              Sign in
            </Link>
            <Link href="/request-access" className="hover:text-foreground">
              Sign up
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
