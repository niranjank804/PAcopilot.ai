import { Check, Sparkles } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "Pricing — PA-Copilot",
  description:
    "Plans for PA-Copilot, the AI engineering copilot for IBM Planning Analytics.",
};

interface Plan {
  key: string;
  name: string;
  description: string;
  monthly_token_limit: number | null;
  max_users: number | null;
  max_connections: number | null;
  features: string[];
  price_label: string;
}

// Rendered on the server from the same catalog the backend enforces, so the
// published entitlements and the enforced ones cannot drift. If the API is
// unreachable the page renders its shell rather than 500-ing — a pricing page
// that errors is worse than one that asks you to get in touch.
async function loadPlans(): Promise<Plan[]> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${base}/billing/plans`, {
      next: { revalidate: 300 },
    });

    if (!response.ok) return [];

    const payload = await response.json();
    return payload?.data ?? [];
  } catch {
    return [];
  }
}

function formatLimit(value: number | null, noun: string): string {
  if (value === null) return `Unlimited ${noun}`;
  if (noun === "tokens") {
    return `${(value / 1_000_000).toLocaleString()}M tokens / month`;
  }
  return `${value.toLocaleString()} ${noun}`;
}

export default async function PricingPage() {
  const plans = await loadPlans();
  const highlighted = "professional";

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Link
            href="/"
            className="flex items-center gap-2 font-semibold tracking-tight"
          >
            <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Sparkles className="size-4" />
            </div>
            PA <span className="text-primary">Copilot</span>
          </Link>
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
        <section className="mx-auto max-w-6xl px-6 pt-20 pb-12 text-center">
          <Badge variant="secondary" className="mb-6">
            Developer preview
          </Badge>
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
            Plans
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
            Every plan includes the full product — grounded generation, live
            compile validation, and human-gated deployment. Plans differ in
            scale, not capability.
          </p>
        </section>

        <section className="mx-auto max-w-6xl px-6 pb-20">
          {plans.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-muted-foreground">
                Plan details aren&apos;t available right now.{" "}
                <Link href="/request-access" className="text-primary underline">
                  Get in touch
                </Link>{" "}
                and we&apos;ll walk you through the options.
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-6 md:grid-cols-3">
              {plans.map((plan) => (
                <Card
                  key={plan.key}
                  className={cn(
                    "flex flex-col",
                    plan.key === highlighted && "border-primary shadow-sm",
                  )}
                >
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle>{plan.name}</CardTitle>
                      {plan.key === highlighted && (
                        <Badge variant="secondary">Most common</Badge>
                      )}
                    </div>
                    <p className="pt-1 text-2xl font-semibold tracking-tight">
                      {plan.price_label}
                    </p>
                    <p className="pt-2 text-sm text-muted-foreground">
                      {plan.description}
                    </p>
                  </CardHeader>

                  <CardContent className="flex flex-1 flex-col">
                    <ul className="space-y-2 text-sm">
                      <li className="font-medium">
                        {formatLimit(plan.max_users, "users")}
                      </li>
                      <li className="font-medium">
                        {formatLimit(plan.max_connections, "TM1 connections")}
                      </li>
                      <li className="font-medium">
                        {formatLimit(plan.monthly_token_limit, "tokens")}
                      </li>
                    </ul>

                    <ul className="mt-6 space-y-2 border-t border-border/60 pt-6 text-sm text-muted-foreground">
                      {plan.features.map((feature) => (
                        <li key={feature} className="flex gap-2">
                          <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>

                    <Link
                      href="/request-access"
                      className={cn(
                        buttonVariants({
                          variant:
                            plan.key === highlighted ? "default" : "outline",
                        }),
                        "mt-8 w-full",
                      )}
                    >
                      {plan.key === "trial" ? "Start free" : "Get in touch"}
                    </Link>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          <p className="mx-auto mt-10 max-w-2xl text-center text-sm text-muted-foreground">
            PA-Copilot is in developer preview. Usage limits are metered per
            organization; nothing is charged automatically, and connecting a
            production Planning Analytics environment is something we&apos;d
            walk through with your IT and security teams first.
          </p>
        </section>
      </main>

      <footer className="border-t border-border/60 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 text-sm text-muted-foreground sm:flex-row">
          <span>© {new Date().getFullYear()} PA-Copilot</span>
          <div className="flex gap-6">
            <Link href="/" className="hover:text-foreground">
              Home
            </Link>
            <Link href="/login" className="hover:text-foreground">
              Sign in
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
