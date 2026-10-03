import { Badge } from "@/components/ui/badge";
import type { Environment } from "@/lib/types";

export const ENVIRONMENT_HELP: Record<Environment, string> = {
  dev: "DEV — changes need the deploy right; the assistant may draft here.",
  qa: "QA — changes need the 'deploy to QA' right.",
  prod: "PROD — changes need the 'deploy to PROD' right and a second person to approve; the assistant is read-only here.",
};

/** DEV / QA / PROD, written out — the label carries the meaning, the
 * colour only reinforces it. */
export function EnvironmentBadge({ environment }: { environment?: Environment | null }) {
  const env = environment ?? "dev";
  return (
    <Badge
      variant={env === "prod" ? "destructive" : env === "qa" ? "warning" : "outline"}
      title={ENVIRONMENT_HELP[env]}
    >
      {env.toUpperCase()}
    </Badge>
  );
}
