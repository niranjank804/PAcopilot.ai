"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * The one renderer for model-written Markdown.
 *
 * Lifted out of the chat page after the Knowledge Base showed its answers
 * as plain text — `**bold**` printed literally — while Chat, given the
 * same model output, rendered it. Both surfaces receive Markdown from
 * the same backend, so they must render it the same way, and the way
 * to guarantee that is one component rather than two copies of a
 * components map that drift.
 *
 * Sizing is tuned for a chat bubble or answer card rather than a full
 * document, which is why this maps elements by hand instead of pulling
 * in the typography plugin for a handful of small blocks. Headings are
 * deliberately stepped down (h1 → h3) so a model that opens with a
 * title does not shout inside a card.
 */
const components: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-0.5 pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-0.5 pl-4 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  h1: ({ children }) => (
    <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h4>
  ),
  code: ({ children, className }) =>
    className ? (
      <pre className="mb-2 overflow-x-auto rounded bg-black/10 p-2 text-xs last:mb-0">
        <code>{children}</code>
      </pre>
    ) : (
      <code className="rounded bg-black/10 px-1 py-0.5 text-xs">{children}</code>
    ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="underline underline-offset-2"
    >
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border-b px-2 py-1">{children}</td>,
};

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </ReactMarkdown>
  );
}
