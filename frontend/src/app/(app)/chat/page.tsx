"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Check,
  FileText,
  Loader2,
  MessageSquarePlus,
  Mic,
  MicOff,
  Paperclip,
  Pencil,
  Search,
  Send,
  ShieldAlert,
  Trash2,
  User,
  Wrench,
  X,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { ChangeActionCard } from "@/components/change-action-card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest, streamRequest } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  AgentInfo,
  ChatAttachmentInput,
  ConversationSummary,
  MessageResponse,
  StreamEvent,
  ToolExecutionResponse,
} from "@/lib/types";

const NO_AGENT = "none";

const ACCEPTED_ATTACHMENT_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".docx"];
const MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024;
const MAX_ATTACHMENTS = 5;

interface ToolCallEvent {
  name: string;
  status: "success" | "error";
}

interface ThreadMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  totalTokens?: number;
  estimatedCostUsd?: number;
  toolCalls?: ToolCallEvent[];
  isError?: boolean;
  attachmentNames?: string[];
}

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const number = new Intl.NumberFormat("en-US").format;

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// Clicking a tool badge fills the input with a starter prompt instead of
// the user having to type or copy-paste one — placeholders in [brackets]
// stand in for the specific object name only the user knows, since most
// of these tools take a required argument we can't guess. Never
// auto-sends: the user still reviews/edits before hitting Send.
const TOOL_PROMPTS: Record<string, string> = {
  list_cubes: "List all cubes in the model.",
  get_cube: "Show me details about the [cube name] cube.",
  get_cube_rules: "Show me the rules for the [cube name] cube.",
  list_dimensions: "List all dimensions in the model.",
  get_dimension: "Show me details about the [dimension name] dimension.",
  list_dimension_elements: "List the elements in the [dimension name] dimension.",
  list_processes: "List all processes.",
  get_process: "Show me the [process name] process.",
  list_chores: "List all chores.",
  get_chore: "Show me the [chore name] chore.",
  get_object_relationships: "What are the relationships for [object name]?",
  find_dependents: "What depends on [object name]?",
  find_dependencies: "What does [object name] depend on?",
  dependency_path: "Is there a dependency path between [object A] and [object B]?",
  find_unused_objects: "Find unused objects in the model.",
  execute_mdx: "Run this MDX query: [paste MDX here]",
  propose_rule_update: "Draft an update to the rules for the [cube name] cube: ",
  propose_process_update: "Draft a new TI process named [process name] that ",
};

function toolPrompt(tool: string): string {
  return TOOL_PROMPTS[tool] ?? `Use ${tool} to `;
}

// AI responses are Markdown (headers, bold, lists) — this maps each
// element to chat-bubble-appropriate sizing rather than pulling in the
// full @tailwindcss/typography plugin for a handful of small bubbles.
const markdownComponents: Components = {
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

function bucketLabel(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round(
    (startOfDay(now) - startOfDay(date)) / (1000 * 60 * 60 * 24),
  );

  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays <= 7) return "Last 7 days";
  return "Older";
}

const BUCKET_ORDER = ["Today", "Yesterday", "Last 7 days", "Older"];

// Heuristic: TM1 tool arguments carry the referenced object's name under one
// of these keys — surfaced in the Context panel so the AI's reasoning ties
// back to concrete model objects, not just tool names.
const NAME_ARG_KEYS = [
  "cube_name",
  "dimension_name",
  "process_name",
  "chore_name",
  "object_name",
  "name",
  "from_name",
  "to_name",
];

// propose_rule_update / propose_process_update return a small JSON result
// (draft_change_id, status, validation_errors, impact, a fixed disclaimer
// note) — well under the 500-char audit-log truncation limit, so this is
// safe to parse directly rather than needing a dedicated field.
const DRAFT_TOOL_NAMES = new Set(["propose_rule_update", "propose_process_update"]);

function draftChangeId(execution: ToolExecutionResponse): string | null {
  if (!DRAFT_TOOL_NAMES.has(execution.tool_name) || execution.status !== "success") {
    return null;
  }
  if (typeof execution.arguments.connection_id !== "string") return null;

  try {
    const parsed = JSON.parse(execution.result_summary ?? "");
    return typeof parsed.draft_change_id === "string" ? parsed.draft_change_id : null;
  } catch {
    return null;
  }
}

function referencedObjects(
  executions: ToolExecutionResponse[] | undefined,
): { label: string; toolName: string }[] {
  if (!executions?.length) return [];

  const seen = new Set<string>();
  const objects: { label: string; toolName: string }[] = [];

  for (const execution of executions) {
    for (const key of NAME_ARG_KEYS) {
      const value = execution.arguments[key];

      if (typeof value === "string" && value.length > 0 && !seen.has(value)) {
        seen.add(value);
        objects.push({ label: value, toolName: execution.tool_name });
      }
    }
  }

  return objects;
}

export default function ChatPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const [agent, setAgent] = useState<string>(() => searchParams.get("agent") ?? NO_AGENT);
  const [input, setInput] = useState(() => searchParams.get("prompt") ?? "");
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [search, setSearch] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(
    null,
  );
  const [isListening, setIsListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachmentInput[]>(
    [],
  );
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Feature-detect once on mount — SpeechRecognition is only ever touched
  // client-side (SSR has no `window`), same reason the theme toggle in
  // settings/page.tsx waits for a mount effect before rendering anything
  // that depends on browser-only APIs.
  useEffect(() => {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;

    if (!Ctor) return;

    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const transcript = event.results[event.results.length - 1][0].transcript;
      setInput((previous) => (previous ? `${previous} ${transcript}` : transcript));
    };
    recognition.onerror = () => {
      toast.error("Couldn't hear that — try again.");
      setIsListening(false);
    };
    recognition.onend = () => setIsListening(false);

    recognitionRef.current = recognition;
    // Support isn't known until after mount (window.SpeechRecognition is
    // browser-only) — same pattern as settings/page.tsx's theme toggle.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSpeechSupported(true);
  }, []);

  const insertToolPrompt = (tool: string) => {
    setInput(toolPrompt(tool));
    inputRef.current?.focus();
  };

  // No backend support for editing/deleting a sent message or truncating a
  // conversation, so this doesn't try to rewrite history — it just loads the
  // original text back into the composer for the user to revise and send as
  // a normal new message, same as any other edit-and-resubmit affordance.
  const editMessage = (content: string) => {
    setInput(content);
    inputRef.current?.focus();
  };

  const toggleListening = () => {
    const recognition = recognitionRef.current;

    if (!recognition) return;

    if (isListening) {
      recognition.stop();
      setIsListening(false);
    } else {
      recognition.start();
      setIsListening(true);
    }
  };

  const readFileAsBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        // result is "data:<mime>;base64,<data>" — strip the prefix, the
        // backend only wants the raw base64 payload.
        const result = reader.result as string;
        resolve(result.slice(result.indexOf(",") + 1));
      };
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });

  const handleFilesSelected = async (files: FileList | null) => {
    if (!files?.length) return;

    if (pendingAttachments.length + files.length > MAX_ATTACHMENTS) {
      toast.error(`You can attach up to ${MAX_ATTACHMENTS} files per message.`);
      return;
    }

    const accepted: ChatAttachmentInput[] = [];

    for (const file of Array.from(files)) {
      const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();

      if (!ACCEPTED_ATTACHMENT_EXTENSIONS.includes(extension)) {
        toast.error(`"${file.name}" isn't a supported file type (PDF, JPG, PNG, DOCX).`);
        continue;
      }

      if (file.size > MAX_ATTACHMENT_BYTES) {
        toast.error(`"${file.name}" is too large — attachments are capped at 15MB.`);
        continue;
      }

      try {
        const data = await readFileAsBase64(file);
        accepted.push({ filename: file.name, content_type: file.type, data });
      } catch {
        toast.error(`Couldn't read "${file.name}".`);
      }
    }

    setPendingAttachments((previous) => [...previous, ...accepted]);
  };

  const removeAttachment = (filename: string) => {
    setPendingAttachments((previous) => previous.filter((a) => a.filename !== filename));
  };

  const agentsQuery = useQuery({
    queryKey: ["ai-agents"],
    queryFn: () => apiRequest<AgentInfo[]>("/ai/agents"),
  });

  const conversationsQuery = useQuery({
    queryKey: ["ai-conversations"],
    queryFn: () => apiRequest<ConversationSummary[]>("/ai/conversations"),
  });

  const toolExecutionsQuery = useQuery({
    queryKey: ["ai-tool-executions", conversationId],
    queryFn: () =>
      apiRequest<ToolExecutionResponse[]>(
        `/ai/conversations/${conversationId}/tool-executions`,
      ),
    enabled: conversationId !== null,
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiRequest<ConversationSummary>(`/ai/conversations/${id}`, {
        method: "PATCH",
        body: { title },
      }),
    onSuccess: () => {
      setRenamingId(null);
      queryClient.invalidateQueries({ queryKey: ["ai-conversations"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiRequest<null>(`/ai/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      toast.success("Conversation deleted.");
      setDeleteTarget(null);
      if (conversationId === id) {
        newConversation();
      }
      queryClient.invalidateQueries({ queryKey: ["ai-conversations"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const scrollToBottom = () =>
    queueMicrotask(() =>
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }),
    );

  const newConversation = () => {
    setConversationId(null);
    setMessages([]);
  };

  const openConversation = async (id: string) => {
    if (isStreaming) return;

    setConversationId(id);

    try {
      const history = await apiRequest<MessageResponse[]>(
        `/ai/conversations/${id}/messages`,
      );

      setMessages(
        history.map((m) => ({
          id: m.id,
          role: m.role === "user" ? "user" : "assistant",
          content: m.content,
        })),
      );
      scrollToBottom();
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const send = async () => {
    const message = input.trim();

    if ((!message && pendingAttachments.length === 0) || isStreaming) return;

    const attachmentsForThisMessage = pendingAttachments;

    setMessages((previous) => [
      ...previous,
      {
        role: "user",
        content: message,
        attachmentNames: attachmentsForThisMessage.map((a) => a.filename),
      },
      { role: "assistant", content: "", toolCalls: [] },
    ]);
    setInput("");
    setPendingAttachments([]);
    setIsStreaming(true);
    scrollToBottom();

    try {
      const stream = streamRequest<StreamEvent>("/ai/chat/stream", {
        message,
        conversation_id: conversationId ?? undefined,
        agent: agent === NO_AGENT ? undefined : agent,
        enable_tools: agent !== NO_AGENT,
        attachments: attachmentsForThisMessage.length
          ? attachmentsForThisMessage
          : undefined,
      });

      for await (const event of stream) {
        if (event.type === "text_delta") {
          setMessages((previous) => {
            const next = [...previous];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, content: last.content + event.text };
            return next;
          });
          scrollToBottom();
        } else if (event.type === "tool_call") {
          setMessages((previous) => {
            const next = [...previous];
            const last = next[next.length - 1];
            next[next.length - 1] = {
              ...last,
              toolCalls: [
                ...(last.toolCalls ?? []),
                { name: event.tool_name, status: event.tool_status },
              ],
            };
            return next;
          });
        } else if (event.type === "done") {
          const isNewConversation = conversationId === null;
          setConversationId(event.conversation_id);

          setMessages((previous) => {
            const next = [...previous];
            const last = next[next.length - 1];
            next[next.length - 1] = {
              ...last,
              id: event.message_id,
              totalTokens: event.usage.input_tokens + event.usage.output_tokens,
              estimatedCostUsd: event.estimated_cost_usd,
            };
            return next;
          });

          queryClient.invalidateQueries({
            queryKey: ["ai-tool-executions", event.conversation_id],
          });

          if (isNewConversation) {
            queryClient.invalidateQueries({ queryKey: ["ai-conversations"] });
          }
        } else if (event.type === "error") {
          setMessages((previous) => {
            const next = [...previous];
            const last = next[next.length - 1];
            next[next.length - 1] = {
              ...last,
              content: last.content || event.message,
              isError: true,
            };
            return next;
          });
          toast.error(event.message);
        }
      }
    } catch (error) {
      toast.error(errorMessage(error));
      setMessages((previous) => {
        const next = [...previous];
        const last = next[next.length - 1];
        next[next.length - 1] = { ...last, isError: true };
        return next;
      });
    } finally {
      setIsStreaming(false);
      scrollToBottom();
    }
  };

  const selectedAgent = agentsQuery.data?.find((a) => a.name === agent);
  const referenced = referencedObjects(toolExecutionsQuery.data);

  const filteredConversations = (conversationsQuery.data ?? []).filter((c) =>
    (c.title ?? "Untitled conversation")
      .toLowerCase()
      .includes(search.toLowerCase()),
  );

  const buckets = BUCKET_ORDER.map((label) => ({
    label,
    conversations: filteredConversations.filter(
      (c) => bucketLabel(c.created_at) === label,
    ),
  })).filter((bucket) => bucket.conversations.length > 0);

  return (
    <div className="flex h-full gap-4">
      <aside className="flex w-64 shrink-0 flex-col gap-3 border-r pr-4">
        <Button size="sm" onClick={newConversation} disabled={isStreaming}>
          <MessageSquarePlus className="mr-2 h-4 w-4" />
          New conversation
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search conversations"
            className="pl-7"
          />
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto">
          {conversationsQuery.isError ? (
            <p className="text-sm text-destructive">
              Failed to load conversations: {errorMessage(conversationsQuery.error)}
            </p>
          ) : conversationsQuery.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : !filteredConversations.length ? (
            <p className="text-sm text-muted-foreground">
              No conversations yet.
            </p>
          ) : (
            buckets.map((bucket) => (
              <div key={bucket.label}>
                <p className="mb-1 px-1 text-xs font-medium text-muted-foreground">
                  {bucket.label}
                </p>
                <div className="space-y-0.5">
                  {bucket.conversations.map((conversation) => (
                    <div
                      key={conversation.id}
                      className={cn(
                        "group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm hover:bg-accent",
                        conversation.id === conversationId && "bg-accent",
                      )}
                    >
                      {renamingId === conversation.id ? (
                        <>
                          <Input
                            autoFocus
                            value={renameValue}
                            onChange={(event) => setRenameValue(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                renameMutation.mutate({
                                  id: conversation.id,
                                  title: renameValue.trim() || "Untitled conversation",
                                });
                              } else if (event.key === "Escape") {
                                setRenamingId(null);
                              }
                            }}
                            className="h-7 flex-1"
                          />
                          <button
                            type="button"
                            aria-label="Save name"
                            onClick={() =>
                              renameMutation.mutate({
                                id: conversation.id,
                                title: renameValue.trim() || "Untitled conversation",
                              })
                            }
                          >
                            <Check className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                          </button>
                          <button
                            type="button"
                            aria-label="Cancel rename"
                            onClick={() => setRenamingId(null)}
                          >
                            <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => openConversation(conversation.id)}
                            className="flex-1 truncate text-left"
                            title={conversation.title ?? "Untitled conversation"}
                          >
                            {conversation.title || "Untitled conversation"}
                          </button>
                          <button
                            type="button"
                            aria-label="Rename conversation"
                            className="hidden shrink-0 group-hover:block"
                            onClick={() => {
                              setRenamingId(conversation.id);
                              setRenameValue(conversation.title ?? "");
                            }}
                          >
                            <Pencil className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                          </button>
                          <button
                            type="button"
                            aria-label="Delete conversation"
                            className="hidden shrink-0 group-hover:block"
                            onClick={() => setDeleteTarget(conversation)}
                          >
                            <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      <div className="flex flex-1 flex-col gap-4 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">AI Chat</h1>
            <p className="text-sm text-muted-foreground">
              Ask about your TM1 models — pick a specialist agent to enable TM1
              tools.
            </p>
          </div>
          <Select
            value={agent}
            onValueChange={(value) => setAgent(value ?? NO_AGENT)}
          >
            <SelectTrigger className="w-44" aria-label="Agent">
              <SelectValue>
                {(value: string) =>
                  value === NO_AGENT ? "No agent (plain chat)" : titleCase(value)
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_AGENT}>No agent (plain chat)</SelectItem>
              {agentsQuery.data?.map((a) => (
                <SelectItem key={a.name} value={a.name}>
                  {titleCase(a.name)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Card className="flex flex-1 flex-col overflow-hidden">
          <CardContent
            ref={scrollRef}
            className="flex-1 space-y-4 overflow-y-auto py-4"
          >
            {messages.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No messages yet. Start by asking something like &quot;Which cubes
                are in my model?&quot;
              </p>
            ) : (
              messages.map((message, index) => (
                <div
                  key={message.id ?? index}
                  className={cn(
                    "group flex gap-3",
                    message.role === "user" ? "justify-end" : "justify-start",
                  )}
                >
                  {message.role === "assistant" ? (
                    <Bot className="mt-1 h-5 w-5 shrink-0 text-muted-foreground" />
                  ) : null}
                  {message.role === "user" && message.content ? (
                    <button
                      type="button"
                      onClick={() => editMessage(message.content)}
                      className="mt-1 h-fit shrink-0 self-center text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                      aria-label="Edit message"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                  <div className="max-w-[75%] space-y-1.5">
                    {message.attachmentNames?.length ? (
                      <div className="flex flex-wrap justify-end gap-1">
                        {message.attachmentNames.map((name) => (
                          <Badge key={name} variant="outline" className="gap-1">
                            <FileText className="h-3 w-3" />
                            {name}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                    {message.toolCalls?.length ? (
                      <div className="flex flex-wrap gap-1">
                        {message.toolCalls.map((call, callIndex) => (
                          <Badge
                            key={callIndex}
                            variant={call.status === "error" ? "destructive" : "secondary"}
                            className="gap-1"
                          >
                            <Wrench className="h-3 w-3" />
                            {call.name}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                    <div
                      className={cn(
                        "rounded-lg px-3 py-2 text-sm [&_pre]:whitespace-pre-wrap",
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : message.isError
                            ? "bg-destructive/10 text-destructive"
                            : "bg-muted",
                      )}
                    >
                      {message.content ? (
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={markdownComponents}
                        >
                          {message.content}
                        </ReactMarkdown>
                      ) : message.role === "assistant" &&
                        isStreaming &&
                        index === messages.length - 1 ? (
                        "…"
                      ) : null}
                      {message.totalTokens ? (
                        <div className="mt-2 text-xs text-muted-foreground">
                          {number(message.totalTokens)} tokens ·{" "}
                          {message.estimatedCostUsd !== undefined
                            ? currency.format(message.estimatedCostUsd)
                            : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {message.role === "user" ? (
                    <User className="mt-1 h-5 w-5 shrink-0 text-muted-foreground" />
                  ) : null}
                </div>
              ))
            )}
          </CardContent>
          <div className="border-t p-4">
            {pendingAttachments.length ? (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {pendingAttachments.map((a) => (
                  <Badge key={a.filename} variant="secondary" className="gap-1">
                    <FileText className="h-3 w-3" />
                    {a.filename}
                    <button
                      type="button"
                      aria-label={`Remove ${a.filename}`}
                      onClick={() => removeAttachment(a.filename)}
                    >
                      <X className="h-3 w-3 hover:text-destructive" />
                    </button>
                  </Badge>
                ))}
              </div>
            ) : null}
            <div className="flex items-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_ATTACHMENT_EXTENSIONS.join(",")}
              className="hidden"
              onChange={(event) => {
                handleFilesSelected(event.target.files);
                event.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              aria-label="Attach files"
              title="Attach PDF, JPG, PNG, or DOCX"
            >
              <Paperclip className="h-4 w-4" />
            </Button>
            <Textarea
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send();
                }
              }}
              placeholder="Ask about cubes, processes, dependencies..."
              className="min-h-[44px] flex-1 resize-none"
              aria-label="Message"
              disabled={isStreaming}
            />
            {speechSupported ? (
              <Button
                type="button"
                variant={isListening ? "destructive" : "outline"}
                onClick={toggleListening}
                disabled={isStreaming}
                aria-label={isListening ? "Stop voice input" : "Start voice input"}
                title={isListening ? "Stop voice input" : "Ask by voice"}
              >
                {isListening ? (
                  <MicOff className="h-4 w-4 animate-pulse" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </Button>
            ) : null}
            <Button
              onClick={send}
              disabled={isStreaming || (!input.trim() && pendingAttachments.length === 0)}
              aria-label="Send message"
            >
              {isStreaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
            </div>
          </div>
        </Card>
      </div>

      <aside className="w-72 shrink-0 space-y-4 overflow-y-auto border-l pl-4">
        <div>
          <h2 className="mb-2 text-sm font-semibold">Agent</h2>
          {selectedAgent ? (
            <Card>
              <CardContent className="space-y-2 py-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">
                    {titleCase(selectedAgent.name)}
                  </span>
                  <Badge variant="secondary">
                    up to {selectedAgent.max_tool_rounds} rounds
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {selectedAgent.description}
                </p>
                {selectedAgent.tool_names?.length ? (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      Allowed tools — click one to start a prompt
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {selectedAgent.tool_names.map((tool) => (
                        <button
                          key={tool}
                          type="button"
                          onClick={() => insertToolPrompt(tool)}
                        >
                          <Badge
                            variant="outline"
                            className="cursor-pointer text-xs hover:bg-accent"
                          >
                            {tool}
                          </Badge>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                {selectedAgent.safety_notes?.length ? (
                  <div>
                    <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                      <ShieldAlert className="h-3 w-3" />
                      Safety rules
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                      {selectedAgent.safety_notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <p className="text-xs text-muted-foreground">
              Select a specialist agent to see its allowed tools and safety
              rules.
            </p>
          )}
        </div>

        <Separator />

        <div>
          <h2 className="mb-2 text-sm font-semibold">Tool Execution Timeline</h2>
          {!conversationId ? (
            <p className="text-xs text-muted-foreground">
              Tool calls in this conversation will appear here once you send a
              message.
            </p>
          ) : toolExecutionsQuery.isError ? (
            <p className="text-xs text-destructive">
              Failed to load tool executions.
            </p>
          ) : toolExecutionsQuery.isPending ? (
            <div className="space-y-1.5">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
            </div>
          ) : !toolExecutionsQuery.data?.length ? (
            <p className="text-xs text-muted-foreground">
              No tool calls in this conversation yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {toolExecutionsQuery.data.map((execution) => {
                const changeId = draftChangeId(execution);

                return (
                  <li key={execution.id} className="text-xs">
                    <div className="flex items-center gap-1.5">
                      {execution.status === "success" ? (
                        <Check className="h-3 w-3 shrink-0 text-primary" />
                      ) : (
                        <X className="h-3 w-3 shrink-0 text-destructive" />
                      )}
                      <span className="font-medium">{execution.tool_name}</span>
                      <span className="ml-auto text-muted-foreground">
                        {execution.duration_ms}ms
                      </span>
                    </div>
                    {execution.error_message ? (
                      <p className="pl-4.5 text-destructive">
                        {execution.error_message}
                      </p>
                    ) : execution.result_summary ? (
                      <p className="pl-4.5 text-muted-foreground">
                        {execution.result_summary}
                      </p>
                    ) : null}
                    {changeId ? (
                      <div className="mt-1.5 pl-4.5">
                        <ChangeActionCard
                          connectionId={execution.arguments.connection_id as string}
                          changeId={changeId}
                        />
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <Separator />

        <div>
          <h2 className="mb-2 text-sm font-semibold">Referenced Objects</h2>
          {!referenced.length ? (
            <p className="text-xs text-muted-foreground">
              TM1 objects the AI has looked up will appear here.
            </p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {referenced.map((object) => (
                <Badge
                  key={object.label}
                  variant="outline"
                  title={object.toolName}
                  className="text-xs"
                >
                  {object.label}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </aside>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete &quot;{deleteTarget?.title ?? "Untitled conversation"}&quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the conversation and its message
              history.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
