"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Generated TI, MDX and rule code — never a paragraph container.
 *
 * TM1 code is read as machine output: a dark surface, a monospace face
 * and a header naming the language keep it separate from the model's
 * explanation around it, and the copy button is the thing people reach
 * for most. The surface stays dark in both themes on purpose (see the
 * --color-code note in globals.css).
 */
export function CodeBlock({
  code,
  language,
  title,
  actions,
  showLineNumbers = false,
  className,
}: {
  code: string;
  language?: string;
  title?: ReactNode;
  actions?: ReactNode;
  showLineNumbers?: boolean;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;

    const timer = setTimeout(() => setCopied(false), 2000);

    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      // Clipboard access can be refused (insecure context, permission
      // policy). The code is on screen and selectable either way, so
      // this stays silent rather than throwing a toast at someone.
    }
  };

  const lines = code.replace(/\n$/, "").split("\n");

  return (
    <figure
      className={cn(
        "overflow-hidden rounded-xl border border-code-border bg-code text-code-foreground",
        className,
      )}
    >
      <figcaption className="flex items-center justify-between gap-2 border-b border-code-border px-3 py-2">
        <span className="truncate font-mono text-xs text-code-foreground/60">
          {title ?? language ?? "code"}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          <Button
            type="button"
            size="xs"
            variant="ghost"
            onClick={copy}
            aria-label={copied ? "Copied" : "Copy code"}
            className="text-code-foreground/70 hover:bg-white/10 hover:text-code-foreground"
          >
            {copied ? (
              <Check className="size-3" aria-hidden />
            ) : (
              <Copy className="size-3" aria-hidden />
            )}
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </figcaption>

      <pre className="overflow-x-auto px-3 py-3 font-mono text-[0.8125rem] leading-6">
        <code>
          {showLineNumbers
            ? lines.map((line, index) => (
                <span key={index} className="grid grid-cols-[2.5rem_1fr]">
                  <span
                    className="select-none pr-3 text-right text-code-foreground/35"
                    aria-hidden
                  >
                    {index + 1}
                  </span>
                  <span>{line || " "}</span>
                </span>
              ))
            : code}
        </code>
      </pre>
    </figure>
  );
}
