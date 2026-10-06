import {
  AudioLines,
  BellRing,
  FileText,
  Fingerprint,
  GitBranch,
  HeartPulse,
  Image as ImageIcon,
  KeyRound,
  Layers,
  LayoutDashboard,
  LineChart,
  Lock,
  Network,
  Shield,
  ShieldCheck,
  Sigma,
  Siren,
  Sparkles,
  Terminal,
  UserCheck,
  UsersRound,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { BackendWarmup } from "@/components/backend-warmup";
import { ProductDemo } from "@/components/landing/product-demo";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const FEATURES = [
  {
    icon: LayoutDashboard,
    title: "Command Center",
    description:
      "One screen for what needs attention: model health, open incidents and alerts, failed and slow processes, changes awaiting approval, and AI cost.",
  },
  {
    icon: Terminal,
    title: "TI Script Assistant",
    description:
      "Generate, refactor, review and debug TurboIntegrator processes with specialist agents that read your live model.",
  },
  {
    icon: Sigma,
    title: "Rules & Feeders Intelligence",
    description:
      "Explain, trace and validate rule and feeder logic in plain language before it ever touches production.",
  },
  {
    icon: LineChart,
    title: "Visualize",
    description:
      "Ask a question in plain English and get the MDX and a live chart back — then pivot it and export to CSV, Excel or an image.",
  },
  {
    icon: ShieldCheck,
    title: "Governed write-back",
    description:
      "The AI drafts rule, process and cell-value changes; a person with the right DEV, QA or PROD rights executes them, with a second approver on PROD and rollback to the saved state.",
  },
  {
    icon: Siren,
    title: "Incident investigation",
    description:
      "Report wrong numbers or a failed load and get ranked suspects — recent changes, failed runs, model differences — with the evidence and a suggested next step.",
  },
  {
    icon: BellRing,
    title: "Alerts & monitoring",
    description:
      "Rules that watch for failed or slow processes, dimension growth, security and model changes, and raise alerts in the app and by email. They only read TM1.",
  },
  {
    icon: HeartPulse,
    title: "Model Health",
    description:
      "A health score for the model with the evidence behind every point, plus performance regressions and the slowest loads.",
  },
  {
    icon: Network,
    title: "Dependencies & impact",
    description:
      "Walk the dependency graph across cubes, dimensions, processes and rules, and see what a change or deletion would affect before you make it.",
  },
  {
    icon: UsersRound,
    title: "Team & Engineering Memory",
    description:
      "Work items with their whole story, shared conversations, and the team knowledge TM1 cannot hold — run orders, conventions, cautions.",
  },
  {
    icon: FileText,
    title: "Knowledge Base & Explain Error",
    description:
      "Ground answers in your own documentation, and paste a TM1 error to get the cause and the fix checked against your model.",
  },
  {
    icon: AudioLines,
    title: "Files and voice in chat",
    description:
      "Attach PDFs, screenshots, Word docs or .pro files, or just talk — dictation and hands-free conversation with answers read aloud.",
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
    description:
      "A reviewer with rights for that environment sees the exact diff and its impact; on PROD a second person approves.",
  },
  {
    step: "04",
    title: "Verified & Audited",
    description:
      "Changes are snapshotted before the write, verified after, restored if verification fails, and can be promoted from DEV to QA to PROD.",
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
    title: "Approved access, revocable anytime",
    description:
      "Every new account is approved by an administrator before it can sign in, and can be deactivated at any time after.",
  },
  {
    icon: Lock,
    title: "No unattended writes",
    description:
      "AI agents can only draft changes. Executing or rolling back a change always requires an explicit human action.",
  },
  {
    icon: Layers,
    title: "DEV, QA and PROD rights",
    description:
      "Each connection is marked DEV, QA or PROD. Deploying needs the right for that environment, PROD needs a second approver, and the AI is read-only on PROD.",
  },
  {
    icon: KeyRound,
    title: "Encrypted credentials, private networks",
    description:
      "TM1 credentials are encrypted at rest and never shown again. A gateway reaches servers inside your network by connecting out — no inbound firewall port.",
  },
  {
    icon: Fingerprint,
    title: "Google Sign-In",
    description:
      "Sign in with your Google account — a PA-Copilot account is created automatically on first sign-in, no separate password to manage.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <BackendWarmup />
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2 font-semibold tracking-tight">
            <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Sparkles className="size-4" />
            </div>
            PA <span className="text-primary">Copilot</span>
          </div>
          <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
            <a href="#demo" className="hover:text-foreground">
              Demo
            </a>
            <a href="#platform" className="hover:text-foreground">
              Platform
            </a>
            <a href="#workflow" className="hover:text-foreground">
              Workflow
            </a>
            <a href="#security" className="hover:text-foreground">
              Security
            </a>
            <Link href="/pricing" className="hover:text-foreground">
              Pricing
            </Link>
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
          {/* Says what the product is for, rather than what stage its
              development is at. "Now in beta testing" told a visitor
              about our roadmap; this tells them whether they are the
              intended reader. Per-feature maturity is still stated
              honestly where it applies — the capability registry marks
              report automation a Developer Preview, and the pricing
              matrix reflects that. */}
          <Badge variant="secondary" className="mb-6">
            Built for TM1 and Planning Analytics teams
          </Badge>
          <h1 className="mx-auto max-w-3xl text-4xl font-bold tracking-tight text-balance sm:text-5xl">
            An AI engineering copilot for{" "}
            <span className="text-primary">IBM Planning Analytics</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground text-balance">
            Write and debug TI, explain rules and errors, chart data from a
            question, investigate incidents and watch your servers — and draft TM1
            changes with a human always in control of what actually gets written.
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
          <a
            href="#demo"
            className="mt-5 inline-block text-sm font-medium text-primary hover:underline"
          >
            See a demo ↓
          </a>
        </section>

        <section
          id="demo"
          aria-labelledby="demo-heading"
          className="scroll-mt-20 border-t border-border/60 py-20"
        >
          <div className="mx-auto max-w-6xl px-6">
            <div className="mx-auto mb-10 max-w-2xl text-center">
              <h2 id="demo-heading" className="text-3xl font-bold tracking-tight">
                See it work
              </h2>
              <p className="mt-3 text-muted-foreground">
                From a wrong total to a reviewed fix, from a question to a chart,
                and from an incident to its likely cause — the way it runs inside{" "}
                <span className="whitespace-nowrap">PA-Copilot</span>.
              </p>
            </div>
            <ProductDemo />
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
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
              Request an account and an administrator lets you in — no sales
              call.
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
          <div className="flex flex-wrap items-center justify-center gap-4">
            <Link href="/privacy" className="hover:text-foreground">
              Privacy
            </Link>
            <Link href="/terms" className="hover:text-foreground">
              Terms
            </Link>
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
