"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, Send, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest, uploadRequest } from "@/lib/api-client";
import type {
  AgentInfo,
  AskResponseBody,
  ExplainErrorResponseBody,
  KnowledgeDocument,
} from "@/lib/types";

const NO_AGENT = "none";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  completed: "default",
  processing: "secondary",
  failed: "destructive",
};

const SEVERITY_VARIANT: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  critical: "destructive",
  high: "destructive",
  medium: "secondary",
  low: "outline",
  unknown: "outline",
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeDocument | null>(null);
  const [agent, setAgent] = useState<string>(NO_AGENT);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<AskResponseBody | null>(null);
  const [errorText, setErrorText] = useState("");
  const [errorAnswer, setErrorAnswer] =
    useState<ExplainErrorResponseBody | null>(null);

  const documentsQuery = useQuery({
    queryKey: ["knowledge-documents"],
    queryFn: () => apiRequest<KnowledgeDocument[]>("/knowledge/documents"),
  });

  const agentsQuery = useQuery({
    queryKey: ["ai-agents"],
    queryFn: () => apiRequest<AgentInfo[]>("/ai/agents"),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return uploadRequest<KnowledgeDocument>("/knowledge/documents", formData);
    },
    onSuccess: (document) => {
      toast.success(`"${document.filename}" uploaded.`);
      queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (document: KnowledgeDocument) =>
      apiRequest<null>(`/knowledge/documents/${document.id}`, { method: "DELETE" }),
    onSuccess: (_, document) => {
      toast.success(`"${document.filename}" deleted.`);
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const askMutation = useMutation({
    mutationFn: () =>
      apiRequest<AskResponseBody>("/knowledge/ask", {
        method: "POST",
        body: {
          query,
          agent: agent === NO_AGENT ? undefined : agent,
        },
      }),
    onSuccess: (result) => setAnswer(result),
    onError: (error) => toast.error(errorMessage(error)),
  });

  const explainErrorMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExplainErrorResponseBody>("/knowledge/explain-error", {
        method: "POST",
        body: { error_text: errorText },
      }),
    onSuccess: (result) => setErrorAnswer(result),
    onError: (error) => toast.error(errorMessage(error)),
  });

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) uploadMutation.mutate(file);
    event.target.value = "";
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Knowledge Base
          </h1>
          <p className="text-sm text-muted-foreground">
            Upload your organization&apos;s TM1 documentation so the AI can
            ground answers in it — combine with a specialist agent to draw
            on the live model too.
          </p>
        </div>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="hidden"
            onChange={handleFileChange}
          />
          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Upload document
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Documents</CardTitle>
          <CardDescription>PDF, DOCX, TXT, or Markdown.</CardDescription>
        </CardHeader>
        <CardContent>
          {documentsQuery.isError ? (
            <p className="py-6 text-center text-sm text-destructive">
              Failed to load documents: {errorMessage(documentsQuery.error)}
            </p>
          ) : documentsQuery.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : !documentsQuery.data?.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No documents yet. Upload one to get started.
            </p>
          ) : (
            <ul className="divide-y">
              {documentsQuery.data.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center justify-between py-2.5 text-sm"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate font-medium">{doc.filename}</span>
                    <Badge variant={STATUS_VARIANT[doc.processing_status] ?? "outline"}>
                      {doc.processing_status}
                    </Badge>
                    {doc.error_message ? (
                      <span className="truncate text-xs text-destructive">
                        {doc.error_message}
                      </span>
                    ) : null}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setDeleteTarget(doc)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ask</CardTitle>
          <CardDescription>
            Answers are grounded in your uploaded documents. Pick an agent
            to also let it use live TM1 tools in the same answer.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1 space-y-2">
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="What does our naming convention say about dimension names?"
                rows={3}
              />
            </div>
            <Select value={agent} onValueChange={(value) => setAgent(value ?? NO_AGENT)}>
              <SelectTrigger className="w-44" aria-label="Agent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_AGENT}>Documents only</SelectItem>
                {agentsQuery.data?.map((a) => (
                  <SelectItem key={a.name} value={a.name}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            onClick={() => askMutation.mutate()}
            disabled={askMutation.isPending || !query.trim()}
          >
            {askMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            Ask
          </Button>

          {answer ? (
            <div className="space-y-3 rounded-md border p-4">
              <p className="whitespace-pre-wrap text-sm">{answer.content}</p>
              <div className="text-xs text-muted-foreground">
                {answer.model} · {answer.usage.total_tokens} tokens
              </div>
              {answer.citations.length ? (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    Sources
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {answer.citations.map((c, i) => (
                      <Badge key={i} variant="outline" className="text-xs">
                        {c.filename} · chunk {c.chunk_index}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No matching document content was found for this question.
                </p>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Explain an error</CardTitle>
          <CardDescription>
            Paste a TM1 error message — the Troubleshooter agent checks the
            real objects it mentions and explains what happened and how to
            fix it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            value={errorText}
            onChange={(e) => setErrorText(e.target.value)}
            placeholder="Could not logon: invalid credentials"
            rows={3}
            className="font-mono text-xs"
          />
          <Button
            onClick={() => explainErrorMutation.mutate()}
            disabled={explainErrorMutation.isPending || !errorText.trim()}
          >
            {explainErrorMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            Explain
          </Button>

          {errorAnswer ? (
            <div className="space-y-3 rounded-md border p-4">
              <div className="flex items-center gap-2">
                <Badge variant={SEVERITY_VARIANT[errorAnswer.severity] ?? "outline"}>
                  {errorAnswer.severity}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {errorAnswer.error_type.replaceAll("_", " ")}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-sm">{errorAnswer.content}</p>
              <div className="text-xs text-muted-foreground">
                {errorAnswer.model} · {errorAnswer.usage.total_tokens} tokens
              </div>
              {errorAnswer.citations.length ? (
                <div className="flex flex-wrap gap-1">
                  {errorAnswer.citations.map((c, i) => (
                    <Badge key={i} variant="outline" className="text-xs">
                      {c.filename} · chunk {c.chunk_index}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete &quot;{deleteTarget?.filename}&quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This removes the document and its indexed content. It cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
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
