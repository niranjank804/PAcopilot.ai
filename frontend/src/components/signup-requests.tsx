"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

interface Signup {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  created_at: string;
  organization_name: string;
  roles: string[];
}

/**
 * Sign-ups from every workspace, for the Super Admin only. Each new
 * person gets a private workspace with nobody else in it to approve
 * them, so the decision is made here. For anyone else the endpoint
 * answers 403 and this renders nothing.
 */
export function SignupRequests() {
  const queryClient = useQueryClient();
  const signups = useQuery({
    queryKey: ["admin-signups"],
    queryFn: () => apiRequest<Signup[]>("/admin/signups"),
    retry: false,
  });

  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approve" | "reject" }) =>
      apiRequest(`/admin/signups/${id}/${decision}`, { method: "POST" }),
    onSuccess: (_data, { decision }) => {
      toast.success(decision === "approve" ? "Approved — they can sign in now." : "Rejected.");
      queryClient.invalidateQueries({ queryKey: ["admin-signups"] });
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Something went wrong."),
  });

  if (signups.error instanceof ApiError && signups.error.status === 403) return null;

  return (
    <Card data-tour="users-signups">
      <CardHeader>
        <CardTitle>Sign-up requests (all workspaces)</CardTitle>
        <CardDescription>
          Everyone who signs up gets their own private workspace — they never
          see your connections, or anyone else&apos;s. They can sign in once
          you approve them here.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {signups.isError ? (
          <p className="py-6 text-center text-sm text-destructive">
            Failed to load sign-up requests.
          </p>
        ) : signups.isPending ? (
          <Skeleton className="h-10 w-full" />
        ) : !signups.data.length ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No sign-ups waiting.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Workspace</TableHead>
                <TableHead>Signed up</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {signups.data.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">
                    {s.first_name} {s.last_name}
                  </TableCell>
                  <TableCell>{s.email}</TableCell>
                  <TableCell className="text-muted-foreground">{s.organization_name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(s.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="space-x-2 text-right">
                    <Button
                      size="sm"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: s.id, decision: "approve" })}
                    >
                      <Check className="size-4" aria-hidden />
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: s.id, decision: "reject" })}
                    >
                      <X className="size-4" aria-hidden />
                      Reject
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
