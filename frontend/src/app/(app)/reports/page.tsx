"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Loader2, Play, Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { toast } from "sonner";

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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiRequest } from "@/lib/api-client";
import type {
  ReportDefinition,
  ReportWorkbook,
  RunNowResult,
} from "@/lib/report-types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ReportsPage() {
  const queryClient = useQueryClient();

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [workbookId, setWorkbookId] = useState("");
  const [format, setFormat] = useState("xlsx");
  const fileInput = useRef<HTMLInputElement>(null);

  const reports = useQuery({
    queryKey: ["reports"],
    queryFn: () =>
      apiRequest<ReportDefinition[]>("/reports/definitions"),
  });

  const workbooks = useQuery({
    queryKey: ["report-workbooks"],
    queryFn: () => apiRequest<ReportWorkbook[]>("/reports/workbooks"),
  });

  /** Multipart, so it bypasses apiRequest's JSON body handling. */
  const uploadWorkbook = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);

      const token = localStorage.getItem("accessToken");

      const response = await fetch(`${API_URL}/reports/workbooks`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });

      const body = await response.json();

      if (!response.ok || !body.success) {
        throw new ApiError(
          response.status,
          body.error?.code ?? "ERROR",
          body.error?.message ?? "Upload failed",
        );
      }

      return body.data as ReportWorkbook;
    },
    onSuccess: (workbook) => {
      toast.success(`Uploaded ${workbook.filename}`);
      setWorkbookId(workbook.id);
      queryClient.invalidateQueries({ queryKey: ["report-workbooks"] });
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  const createReport = useMutation({
    mutationFn: () =>
      apiRequest<ReportDefinition>("/reports/definitions", {
        method: "POST",
        body: {
          name,
          report_type: "pafe_workbook",
          workbook_id: workbookId,
          output_formats: [format],
        },
      }),
    onSuccess: () => {
      toast.success("Report created");
      setCreateOpen(false);
      setName("");
      setWorkbookId("");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  const runNow = useMutation({
    mutationFn: (reportId: string) =>
      apiRequest<RunNowResult>(`/reports/definitions/${reportId}/run`, {
        method: "POST",
      }),
    onSuccess: (result) => {
      // `created: false` means an identical request in the same minute
      // already queued this run — success, not a duplicate.
      toast.success(
        result.created
          ? "Execution queued"
          : "This report is already queued for this minute",
      );
      queryClient.invalidateQueries({ queryKey: ["report-executions"] });
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
          <p className="text-sm text-muted-foreground">
            Automate the Planning Analytics reports your teams already run
            manually.{" "}
            <Badge variant="outline" className="ml-1">
              Developer preview
            </Badge>
          </p>
        </div>

        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New report
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>PAfE workbook reports</CardTitle>
          <CardDescription>
            Each run is executed by a registered Windows worker with Excel and
            PAfE installed.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {reports.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : reports.data?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Formats</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reports.data.map((report) => (
                  <TableRow key={report.id}>
                    <TableCell className="font-medium">{report.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {report.report_type}
                    </TableCell>
                    <TableCell>
                      {report.output_formats.join(", ").toUpperCase()}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{report.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={runNow.isPending}
                        onClick={() => runNow.mutate(report.id)}
                      >
                        {runNow.isPending &&
                        runNow.variables === report.id ? (
                          <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                        ) : (
                          <Play className="mr-2 h-3 w-3" />
                        )}
                        Run now
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-center text-sm text-muted-foreground">
              <FileSpreadsheet className="mx-auto mb-3 h-8 w-8 opacity-40" />
              No reports yet. Upload a PAfE workbook and create one.
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Runs never start on their own — scheduling and STET approval arrive in
        a later phase. See{" "}
        <Link href="/reports/executions" className="underline">
          execution history
        </Link>
        .
      </p>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New report</DialogTitle>
            <DialogDescription>
              Upload the PAfE workbook this report should refresh.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="report-name">Report name</Label>
              <Input
                id="report-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Monthly P&L"
              />
            </div>

            <div className="space-y-2">
              <Label>Workbook</Label>
              <div className="flex gap-2">
                {/* This Select emits `string | null` on clear, so the
                    setters below normalise rather than widening the state. */}
                <Select
                  value={workbookId}
                  onValueChange={(value) => setWorkbookId(value ?? "")}
                >
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder="Select a workbook" />
                  </SelectTrigger>
                  <SelectContent>
                    {workbooks.data?.map((workbook) => (
                      <SelectItem key={workbook.id} value={workbook.id}>
                        {workbook.name} (v{workbook.version})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <input
                  ref={fileInput}
                  type="file"
                  accept=".xlsx,.xlsm,.xlsb"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];

                    if (file) {
                      uploadWorkbook.mutate(file);
                    }
                  }}
                />

                <Button
                  type="button"
                  variant="outline"
                  disabled={uploadWorkbook.isPending}
                  onClick={() => fileInput.current?.click()}
                >
                  {uploadWorkbook.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <Label>Output format</Label>
              <Select
                value={format}
                onValueChange={(value) => setFormat(value ?? "xlsx")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="xlsx">XLSX</SelectItem>
                  <SelectItem value="pdf">PDF</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!name || !workbookId || createReport.isPending}
              onClick={() => createReport.mutate()}
            >
              {createReport.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Create report
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
