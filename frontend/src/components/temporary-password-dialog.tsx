"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest } from "@/lib/api-client";

export interface TemporaryPasswordIssued {
  id: string;
  username: string;
  temporary_password: string;
  expires_at: string;
}

interface TemporaryPasswordDialogProps {
  person: { id: string; name: string } | null;
  onClose: () => void;
}

/** Super Admin → a one-time password for someone locked out when no reset
 * email can reach them. The password is shown exactly once, here, for the
 * Super Admin to pass on themselves; the audit log records that it was
 * issued and why, never what it was. */
export function TemporaryPasswordDialog({ person, onClose }: TemporaryPasswordDialogProps) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [issued, setIssued] = useState<TemporaryPasswordIssued | null>(null);
  const [copied, setCopied] = useState(false);

  const issue = useMutation({
    mutationFn: (id: string) =>
      apiRequest<TemporaryPasswordIssued>(`/admin/platform/users/${id}/temporary-password`, {
        method: "POST",
        body: { reason },
      }),
    onSuccess: (data) => {
      setIssued(data);
      for (const key of ["platform-users", "platform-audit"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Something went wrong."),
  });

  const close = () => {
    setIssued(null);
    setReason("");
    setCopied(false);
    onClose();
  };

  const copy = async () => {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.temporary_password);
      setCopied(true);
    } catch {
      toast.error("Could not copy. Select the password and copy it by hand.");
    }
  };

  return (
    <Dialog
      open={person !== null}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent>
        <DialogTitle>Temporary password for {person?.name}</DialogTitle>
        {issued ? (
          <div className="space-y-4">
            <DialogDescription>
              Pass this on yourself, by phone or another channel you trust. It is shown only now and
              expires {new Date(issued.expires_at).toLocaleString()}. It signs {person?.name} in for
              one thing: choosing a password of their own.
            </DialogDescription>
            <div className="flex items-center gap-2">
              <code
                data-testid="temporary-password"
                className="flex-1 select-all rounded border bg-muted px-3 py-2 font-mono text-base"
              >
                {issued.temporary_password}
              </code>
              <Button type="button" variant="outline" size="sm" onClick={copy}>
                {copied ? <Check className="mr-1 h-4 w-4" /> : <Copy className="mr-1 h-4 w-4" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Username: <span className="font-mono">{issued.username}</span>. Their other sessions were
              signed out.
            </p>
            <Button type="button" className="w-full" onClick={close}>
              Done
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <DialogDescription>
              For someone who forgot their password when no reset email can reach them. Their current
              password stops working and every session ends. The one-time password you get here signs
              them in once, to choose their own. The audit log records that you did this and why; the
              password itself is never recorded.
            </DialogDescription>
            <div className="space-y-2">
              <Label htmlFor="temporary-password-reason">Reason (goes into the audit log)</Label>
              <Textarea
                id="temporary-password-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Asked by phone on …"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button
                type="button"
                onClick={() => {
                  if (person) issue.mutate(person.id);
                }}
                disabled={issue.isPending}
              >
                {issue.isPending ? "Generating…" : "Generate password"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
