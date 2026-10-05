"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Markdown } from "@/components/markdown";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import { when, type SharedConversation } from "@/lib/team";
import type { MessageResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A conversation a colleague shared, read-only. Continuing it is for its
 * owner; anyone else starts their own in the AI Assistant.
 */
export default function SharedConversationPage() {
  const { id } = useParams<{ id: string }>();

  const messages = useQuery({
    queryKey: ["team", "conversation", id],
    queryFn: () => apiRequest<MessageResponse[]>(`/ai/conversations/${id}/messages`),
  });
  const shared = useQuery({
    queryKey: ["team", "conversations"],
    queryFn: () => apiRequest<SharedConversation[]>("/team/conversations"),
  });
  const summary = shared.data?.find((c) => c.id === id);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Link href="/team" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" />
        Team
      </Link>
      <div>
        <h1 className="page-title">{summary?.title || "Shared conversation"}</h1>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Eye className="h-3.5 w-3.5" aria-hidden />
          Read-only{summary ? ` · shared by ${summary.owner_name} · started ${when(summary.created_at)}` : ""}
        </p>
      </div>

      {messages.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : messages.isError ? (
        <p className="text-sm text-destructive">
          {messages.error instanceof ApiError && messages.error.status === 404
            ? "This conversation is not shared with you, or no longer exists."
            : "Could not load the conversation."}
        </p>
      ) : (
        <ol className="space-y-3">
          {messages.data
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => (
              <li
                key={m.id}
                className={cn(
                  "rounded-lg border p-3 text-sm",
                  m.role === "user" ? "ml-10 bg-muted/50" : "mr-10",
                )}
              >
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {m.role === "user" ? (summary?.owner_name ?? "Question") : "PA-Copilot"} · {when(m.created_at)}
                </p>
                {m.role === "assistant" ? <Markdown>{m.content}</Markdown> : <p className="whitespace-pre-wrap">{m.content}</p>}
              </li>
            ))}
        </ol>
      )}
    </div>
  );
}
