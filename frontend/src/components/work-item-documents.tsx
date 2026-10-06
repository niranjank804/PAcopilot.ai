"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Download, FileText, Pencil, Plus, Printer, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { download } from "@/components/visualize/chart-builder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest, downloadRequest } from "@/lib/api-client";
import { when } from "@/lib/team";

export const DOCUMENT_KINDS: Record<string, string> = {
  requirements: "Requirements",
  clarification_email: "Clarification email",
  design: "Design",
  code: "Code",
  test_plan: "Test plan",
  test_results: "Test results",
  evidence: "Evidence",
  delivery: "Delivery document",
  completion_email: "Completion email",
  notes: "Notes",
};

export interface DocumentSummary {
  id: string;
  kind: string;
  title: string;
  version: number;
  drafted_by_assistant: boolean;
  created_at: string;
  updated_at: string;
}

interface DocumentFull extends DocumentSummary {
  content: string;
}

function message(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

/**
 * The documents a work item has produced — clarification email, design,
 * test plan and results, delivery document — drafted by the assistant or
 * written here, read and edited in place, and downloaded as Word or
 * Markdown, or printed to PDF.
 */
export function WorkItemDocuments({ workItemId, reference }: { workItemId: string; reference: string }) {
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ kind: string; title: string; content: string } | null>(null);

  const listKey = ["team", "work-item", workItemId, "documents"];
  const documents = useQuery({
    queryKey: listKey,
    queryFn: () => apiRequest<DocumentSummary[]>(`/team/work-items/${workItemId}/documents`),
  });
  const opened = useQuery({
    queryKey: [...listKey, openId],
    queryFn: () => apiRequest<DocumentFull>(`/team/work-items/${workItemId}/documents/${openId}`),
    enabled: openId !== null,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: listKey });
    queryClient.invalidateQueries({ queryKey: ["team", "work-item", workItemId] });
  };

  const save = useMutation({
    mutationFn: (body: { kind: string; title: string; content: string }) =>
      apiRequest<DocumentFull>(`/team/work-items/${workItemId}/documents`, { method: "POST", body }),
    onSuccess: (document) => {
      toast.success(`Saved "${document.title}" (version ${document.version}).`);
      setEditing(null);
      setOpenId(document.id);
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const remove = useMutation({
    mutationFn: (documentId: string) =>
      apiRequest(`/team/work-items/${workItemId}/documents/${documentId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Deleted.");
      setOpenId(null);
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const fetchFile = async (document: DocumentSummary, format: "docx" | "md") => {
    const response = await downloadRequest(
      `/team/work-items/${workItemId}/documents/${document.id}/download?format=${format}`,
    );
    if (!response.ok) {
      toast.error(`Download failed (HTTP ${response.status}).`);
      return;
    }
    const name = `${reference} - ${document.title}.${format}`.replace(/[\\/:*?"<>|]+/g, "_");
    download(name, await response.blob(), response.headers.get("content-type") ?? "application/octet-stream");
  };

  const current = opened.data;

  return (
    <Card data-tour="work-item-documents">
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="text-base">Documents</CardTitle>
          <CardDescription>
            Clarification email, design, test plan and results, delivery document. The assistant
            drafts them when you work this item in chat; read, edit and download them here.
          </CardDescription>
        </div>
        <Button size="sm" variant="outline" onClick={() => setEditing({ kind: "notes", title: "", content: "" })}>
          <Plus className="mr-1.5 h-3.5 w-3.5" /> New
        </Button>
      </CardHeader>
      <CardContent>
        {documents.data?.length ? (
          <ul className="divide-y">
            {documents.data.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-3 py-2">
                <button
                  type="button"
                  className="flex min-w-0 items-center gap-2 text-left text-sm hover:underline"
                  onClick={() => setOpenId(d.id)}
                >
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate font-medium">{d.title}</span>
                  <Badge variant="secondary">{DOCUMENT_KINDS[d.kind] ?? d.kind}</Badge>
                  {d.drafted_by_assistant ? (
                    <Badge variant="outline" title="Drafted by the assistant">
                      <Bot className="mr-1 h-3 w-3" /> draft
                    </Badge>
                  ) : null}
                </button>
                <span className="shrink-0 text-xs text-muted-foreground">
                  v{d.version} · {when(d.updated_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            No documents yet. Use <span className="font-medium">Work this PBI</span> to have the
            assistant draft them, or add one with New.
          </p>
        )}
      </CardContent>

      <Dialog open={openId !== null && editing === null} onOpenChange={(open) => !open && setOpenId(null)}>
        <DialogContent className="max-h-[90vh] w-[min(60rem,calc(100vw-2rem))] max-w-none overflow-y-auto sm:max-w-none">
          <DialogTitle>
            {current ? `${current.title} · v${current.version}` : "Loading…"}
          </DialogTitle>
          {current ? (
            <>
              <div className="flex flex-wrap gap-2 print:hidden">
                <Button size="sm" variant="outline" onClick={() => fetchFile(current, "docx")}>
                  <Download className="mr-1.5 h-3.5 w-3.5" /> Word
                </Button>
                <Button size="sm" variant="outline" onClick={() => fetchFile(current, "md")}>
                  <Download className="mr-1.5 h-3.5 w-3.5" /> Markdown
                </Button>
                <Button size="sm" variant="outline" onClick={() => window.print()}>
                  <Printer className="mr-1.5 h-3.5 w-3.5" /> Print / PDF
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setEditing({ kind: current.kind, title: current.title, content: current.content })}
                >
                  <Pencil className="mr-1.5 h-3.5 w-3.5" /> Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={remove.isPending}
                  onClick={() => window.confirm(`Delete "${current.title}"?`) && remove.mutate(current.id)}
                >
                  <Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" /> Delete
                </Button>
              </div>
              <div className="print-area rounded-md border p-4 text-sm">
                <Markdown>{current.content}</Markdown>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="max-h-[90vh] w-[min(60rem,calc(100vw-2rem))] max-w-none overflow-y-auto sm:max-w-none">
          <DialogTitle>{editing?.title ? `Edit "${editing.title}"` : "New document"}</DialogTitle>
          {editing ? (
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="doc-title">Title</Label>
                  <Input
                    id="doc-title"
                    value={editing.title}
                    maxLength={200}
                    onChange={(event) => setEditing({ ...editing, title: event.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="doc-kind">Kind</Label>
                  <select
                    id="doc-kind"
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={editing.kind}
                    onChange={(event) => setEditing({ ...editing, kind: event.target.value })}
                  >
                    {Object.entries(DOCUMENT_KINDS).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="doc-content">Content (Markdown)</Label>
                <Textarea
                  id="doc-content"
                  className="min-h-[50vh] font-mono text-xs"
                  value={editing.content}
                  onChange={(event) => setEditing({ ...editing, content: event.target.value })}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
                <Button
                  disabled={save.isPending || !editing.title.trim() || !editing.content.trim()}
                  onClick={() => save.mutate(editing)}
                >
                  Save
                </Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
