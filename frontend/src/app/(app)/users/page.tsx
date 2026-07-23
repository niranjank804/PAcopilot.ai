"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldOff, UserCheck, X } from "lucide-react";
import { useState } from "react";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiRequest } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type { AppUser, RegistrationStatus, RoleInfo } from "@/lib/types";

const STATUS_VARIANT: Record<
  RegistrationStatus,
  "default" | "secondary" | "destructive"
> = {
  approved: "default",
  pending: "secondary",
  rejected: "destructive",
};

const NO_ROLE = "none";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function ApproveRow({ user, roles }: { user: AppUser; roles: RoleInfo[] }) {
  const queryClient = useQueryClient();
  const [roleId, setRoleId] = useState<string>(NO_ROLE);

  const approveMutation = useMutation({
    mutationFn: () =>
      apiRequest<AppUser>(`/users/${user.id}/approve`, {
        method: "POST",
        body: { role_id: roleId === NO_ROLE ? undefined : roleId },
      }),
    onSuccess: () => {
      toast.success(`Approved ${user.username}.`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      apiRequest<AppUser>(`/users/${user.id}/reject`, { method: "POST" }),
    onSuccess: () => {
      toast.success(`Rejected ${user.username}.`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const isPending = approveMutation.isPending || rejectMutation.isPending;

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">
          {user.first_name} {user.last_name}
        </div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
      </TableCell>
      <TableCell className="font-mono text-xs">{user.username}</TableCell>
      <TableCell>
        <Select value={roleId} onValueChange={(v) => setRoleId(v ?? NO_ROLE)}>
          <SelectTrigger className="w-36" aria-label="Role to assign">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_ROLE}>No role yet</SelectItem>
            {roles.map((role) => (
              <SelectItem key={role.id} value={role.id}>
                {role.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-2">
          <Button
            size="sm"
            disabled={isPending}
            onClick={() => approveMutation.mutate()}
          >
            <Check className="mr-1 h-3.5 w-3.5" />
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={isPending}
            onClick={() => rejectMutation.mutate()}
          >
            <X className="mr-1 h-3.5 w-3.5" />
            Reject
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

function MemberRow({ user, isSelf }: { user: AppUser; isSelf: boolean }) {
  const queryClient = useQueryClient();
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  const deactivateMutation = useMutation({
    mutationFn: () =>
      apiRequest<AppUser>(`/users/${user.id}/deactivate`, { method: "POST" }),
    onSuccess: () => {
      toast.success(`Deactivated ${user.username}.`);
      setConfirmDeactivate(false);
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error) => {
      toast.error(errorMessage(error));
      setConfirmDeactivate(false);
    },
  });

  const activateMutation = useMutation({
    mutationFn: () =>
      apiRequest<AppUser>(`/users/${user.id}/activate`, { method: "POST" }),
    onSuccess: () => {
      toast.success(`Reactivated ${user.username}.`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">
          {user.first_name} {user.last_name}
          {isSelf ? (
            <span className="ml-1 text-xs text-muted-foreground">(you)</span>
          ) : null}
        </div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
      </TableCell>
      <TableCell className="font-mono text-xs">{user.username}</TableCell>
      <TableCell>
        <Badge variant={STATUS_VARIANT[user.registration_status]}>
          {user.registration_status}
        </Badge>
      </TableCell>
      <TableCell>{user.is_active ? "Yes" : "No"}</TableCell>
      <TableCell className="text-right">
        {isSelf ? null : user.is_active ? (
          <Button
            size="sm"
            variant="outline"
            disabled={deactivateMutation.isPending}
            onClick={() => setConfirmDeactivate(true)}
          >
            <ShieldOff className="mr-1 h-3.5 w-3.5" />
            Deactivate
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={activateMutation.isPending}
            onClick={() => activateMutation.mutate()}
          >
            <UserCheck className="mr-1 h-3.5 w-3.5" />
            Reactivate
          </Button>
        )}
      </TableCell>

      <AlertDialog open={confirmDeactivate} onOpenChange={setConfirmDeactivate}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Deactivate &quot;{user.username}&quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              They&apos;ll immediately be signed out and unable to log back
              in until reactivated. This doesn&apos;t delete their account
              or data.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deactivateMutation.mutate()}
              disabled={deactivateMutation.isPending}
            >
              {deactivateMutation.isPending ? "Working..." : "Deactivate"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TableRow>
  );
}

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const pendingQuery = useQuery({
    queryKey: ["users", "pending"],
    queryFn: () =>
      apiRequest<AppUser[]>("/users?registration_status=pending"),
  });

  const allUsersQuery = useQuery({
    queryKey: ["users", "all"],
    queryFn: () => apiRequest<AppUser[]>("/users"),
  });

  const rolesQuery = useQuery({
    queryKey: ["roles"],
    queryFn: () => apiRequest<RoleInfo[]>("/roles"),
  });

  const roles = rolesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <p className="text-sm text-muted-foreground">
          Approve or reject access requests, and see everyone in your
          organization.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Pending requests</CardTitle>
          <CardDescription>
            People who submitted &quot;Request access&quot; and are waiting
            for a decision.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pendingQuery.isError ? (
            <p className="py-6 text-center text-sm text-destructive">
              Failed to load: {errorMessage(pendingQuery.error)}
            </p>
          ) : pendingQuery.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : !pendingQuery.data?.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No pending requests.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Username</TableHead>
                  <TableHead>Assign role</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pendingQuery.data.map((user) => (
                  <ApproveRow key={user.id} user={user} roles={roles} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>All members</CardTitle>
        </CardHeader>
        <CardContent>
          {allUsersQuery.isError ? (
            <p className="py-6 text-center text-sm text-destructive">
              Failed to load: {errorMessage(allUsersQuery.error)}
            </p>
          ) : allUsersQuery.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : !allUsersQuery.data?.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No users yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Username</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Active</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {allUsersQuery.data.map((user) => (
                  <MemberRow
                    key={user.id}
                    user={user}
                    isSelf={user.id === currentUser?.id}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
