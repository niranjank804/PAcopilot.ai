"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, Plug, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

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
import { Button, buttonVariants } from "@/components/ui/button";
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
import { Skeleton } from "@/components/ui/skeleton";
import { ConnectionFormFields } from "@/components/connection-form-fields";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { TM1Connection } from "@/lib/types";

const connectionSchema = z
  .object({
    name: z.string().min(1, "Name is required").max(100),
    authentication_type: z.enum(["native", "v12_saas"]),
    address: z.string().min(1, "Address is required"),
    port: z.number().int().min(1).max(65535),
    ssl: z.boolean(),
    username: z.string().optional(),
    password: z.string().min(1, "Password is required"),
    tenant: z.string().optional(),
    database: z.string().optional(),
  })
  .refine((v) => v.authentication_type !== "native" || !!v.username?.trim(), {
    message: "Username is required",
    path: ["username"],
  })
  .refine((v) => v.authentication_type !== "v12_saas" || !!v.tenant?.trim(), {
    message: "Tenant is required",
    path: ["tenant"],
  })
  .refine((v) => v.authentication_type !== "v12_saas" || !!v.database?.trim(), {
    message: "Database is required",
    path: ["database"],
  });

type ConnectionValues = z.infer<typeof connectionSchema>;

// Same shape as connectionSchema, but password is optional — blank means
// "keep the existing credential" rather than "required to submit."
const editSchema = z
  .object({
    name: z.string().min(1, "Name is required").max(100),
    authentication_type: z.enum(["native", "v12_saas"]),
    address: z.string().min(1, "Address is required"),
    port: z.number().int().min(1).max(65535),
    ssl: z.boolean(),
    username: z.string().optional(),
    password: z.string().optional(),
    tenant: z.string().optional(),
    database: z.string().optional(),
  })
  .refine((v) => v.authentication_type !== "native" || !!v.username?.trim(), {
    message: "Username is required",
    path: ["username"],
  })
  .refine((v) => v.authentication_type !== "v12_saas" || !!v.tenant?.trim(), {
    message: "Tenant is required",
    path: ["tenant"],
  })
  .refine((v) => v.authentication_type !== "v12_saas" || !!v.database?.trim(), {
    message: "Database is required",
    path: ["database"],
  });

type EditValues = z.infer<typeof editSchema>;

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

export default function ConnectionsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<TM1Connection | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TM1Connection | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const connectionsQuery = useQuery({
    queryKey: ["tm1-connections"],
    queryFn: () => apiRequest<TM1Connection[]>("/tm1/connections"),
  });

  const {
    register,
    handleSubmit,
    watch,
    reset,
    control,
    formState: { errors },
  } = useForm<ConnectionValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: { authentication_type: "native", port: 8010, ssl: true },
  });

  const authType = watch("authentication_type");

  const {
    register: editRegister,
    handleSubmit: handleEditSubmit,
    watch: editWatch,
    reset: editReset,
    control: editControl,
    formState: { errors: editErrors },
  } = useForm<EditValues>({
    resolver: zodResolver(editSchema),
  });

  const editAuthType = editWatch("authentication_type");

  const createMutation = useMutation({
    mutationFn: (values: ConnectionValues) =>
      apiRequest<TM1Connection>("/tm1/connections", {
        method: "POST",
        body: {
          ...values,
          username: values.authentication_type === "v12_saas" ? "apikey" : values.username,
          tenant: values.authentication_type === "v12_saas" ? values.tenant : undefined,
          database: values.authentication_type === "v12_saas" ? values.database : undefined,
        },
      }),
    onSuccess: (created) => {
      toast.success(`Connection "${created.name}" created.`);
      setCreateOpen(false);
      reset({ authentication_type: "native", port: 8010, ssl: true });
      queryClient.invalidateQueries({ queryKey: ["tm1-connections"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring-tm1-status"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const updateMutation = useMutation({
    mutationFn: (values: EditValues) => {
      if (!editTarget) throw new Error("No connection selected for edit.");

      return apiRequest<TM1Connection>(`/tm1/connections/${editTarget.id}`, {
        method: "PATCH",
        body: {
          ...values,
          password: values.password?.trim() ? values.password : undefined,
          username: values.authentication_type === "v12_saas" ? "apikey" : values.username,
          tenant: values.authentication_type === "v12_saas" ? values.tenant : undefined,
          database: values.authentication_type === "v12_saas" ? values.database : undefined,
        },
      });
    },
    onSuccess: (updated) => {
      toast.success(`Connection "${updated.name}" updated.`);
      setEditTarget(null);
      queryClient.invalidateQueries({ queryKey: ["tm1-connections"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring-tm1-status"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const openEdit = (connection: TM1Connection) => {
    setEditTarget(connection);
    editReset({
      name: connection.name,
      authentication_type: connection.authentication_type,
      address: connection.address,
      port: connection.port,
      ssl: connection.ssl,
      username: connection.username,
      password: "",
      tenant: connection.tenant ?? "",
      database: connection.database ?? "",
    });
  };

  const testMutation = useMutation({
    mutationFn: (connection: TM1Connection) =>
      apiRequest<{ connected: boolean }>(
        `/tm1/connections/${connection.id}/test`,
        { method: "POST" },
      ),
    onMutate: (connection) => setTestingId(connection.id),
    onSettled: () => setTestingId(null),
    onSuccess: (result, connection) => {
      if (result.connected) {
        toast.success(`"${connection.name}" is reachable.`);
      } else {
        toast.error(
          `Could not connect to "${connection.name}" — check address, port, and credentials.`,
        );
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (connection: TM1Connection) =>
      apiRequest<null>(`/tm1/connections/${connection.id}`, {
        method: "DELETE",
      }),
    onSuccess: (_, connection) => {
      toast.success(`Connection "${connection.name}" deleted.`);
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["tm1-connections"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring-tm1-status"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            TM1 Connections
          </h1>
          <p className="text-sm text-muted-foreground">
            Planning Analytics servers this organization can reach.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New Connection
        </Button>
      </div>

      {connectionsQuery.isError ? (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Failed to load connections: {errorMessage(connectionsQuery.error)}
          </CardContent>
        </Card>
      ) : connectionsQuery.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : connectionsQuery.data?.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {connectionsQuery.data.map((connection) => (
            <Card key={connection.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <Link
                    href={`/connections/${connection.id}`}
                    className="hover:underline"
                  >
                    <CardTitle className="text-lg">{connection.name}</CardTitle>
                  </Link>
                  <Badge variant={connection.is_active ? "default" : "secondary"}>
                    {connection.is_active ? "active" : "inactive"}
                  </Badge>
                </div>
                <CardDescription>
                  {connection.address}:{connection.port}
                  {connection.ssl ? " · SSL" : ""} · {connection.username}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex gap-2">
                <Link
                  href={`/connections/${connection.id}`}
                  className={buttonVariants({ variant: "outline", size: "sm" })}
                >
                  View details
                </Link>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={testingId === connection.id}
                  onClick={() => testMutation.mutate(connection)}
                >
                  {testingId === connection.id ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Plug className="mr-2 h-4 w-4" />
                  )}
                  Test
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openEdit(connection)}
                >
                  <Pencil className="mr-2 h-4 w-4" />
                  Edit
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive"
                  onClick={() => setDeleteTarget(connection)}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No TM1 connections yet. Create one to start exploring your model.
          </CardContent>
        </Card>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New TM1 Connection</DialogTitle>
            <DialogDescription>
              Credentials are encrypted at rest; the password is never shown
              again after saving.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={handleSubmit((values) => createMutation.mutate(values))}
            className="space-y-4"
          >
            <ConnectionFormFields
              register={register}
              control={control}
              errors={errors}
              authType={authType}
              passwordLabel={authType === "v12_saas" ? "API key" : "Password"}
            />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Creating..." : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editTarget !== null}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit &quot;{editTarget?.name}&quot;</DialogTitle>
            <DialogDescription>
              Leave the password/API key blank to keep the current credential.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={handleEditSubmit((values) => updateMutation.mutate(values))}
            className="space-y-4"
          >
            <ConnectionFormFields
              register={editRegister}
              control={editControl}
              errors={editErrors}
              authType={editAuthType}
              passwordLabel={editAuthType === "v12_saas" ? "API key" : "Password"}
              passwordPlaceholder="Leave blank to keep current"
            />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditTarget(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "Saving..." : "Save changes"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete &quot;{deleteTarget?.name}&quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This removes the stored connection and its encrypted credentials.
              The TM1 server itself is not touched.
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
