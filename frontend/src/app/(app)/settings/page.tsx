"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

const THEME_OPTIONS = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

export default function SettingsPage() {
  const { user, isLoading } = useAuth();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const queryClient = useQueryClient();

  // Theme isn't known until after hydration — same pattern as ThemeToggle.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");

  // Seeded from the signed-in user once it arrives. Keyed on the values
  // themselves rather than a mount effect so a refreshed profile does not
  // silently overwrite something the user is part-way through typing.
  useEffect(() => {
    setFirstName(user?.first_name ?? "");
    setLastName(user?.last_name ?? "");
  }, [user?.first_name, user?.last_name]);

  const saveProfile = useMutation({
    mutationFn: () =>
      apiRequest("/users/me", {
        method: "PATCH",
        body: { first_name: firstName.trim(), last_name: lastName.trim() },
      }),
    onSuccess: () => {
      toast.success("Profile updated");
      // The header and sidebar read the name from the auth context.
      queryClient.invalidateQueries();
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  const organization = useQuery({
    queryKey: ["organization"],
    queryFn: () =>
      apiRequest<{
        id: string;
        name: string;
        code: string;
        domain: string | null;
        is_active: boolean;
        plan: string;
      }>("/users/organization"),
    // A Viewer has no organization.read, and a 403 is the expected
    // answer rather than a fault — retrying would just repeat it.
    retry: false,
  });

  const [orgName, setOrgName] = useState("");
  const [orgDomain, setOrgDomain] = useState("");

  useEffect(() => {
    setOrgName(organization.data?.name ?? "");
    setOrgDomain(organization.data?.domain ?? "");
  }, [organization.data?.name, organization.data?.domain]);

  const saveOrganization = useMutation({
    mutationFn: () =>
      apiRequest("/users/organization", {
        method: "PATCH",
        body: {
          name: orgName.trim(),
          domain: orgDomain.trim() || null,
        },
      }),
    onSuccess: () => {
      toast.success("Organization updated");
      queryClient.invalidateQueries({ queryKey: ["organization"] });
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Your account and console preferences.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            Account details for the currently signed-in user.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-5 w-64" />
            </div>
          ) : user ? (
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-muted-foreground">Username</dt>
                <dd className="text-sm font-medium">{user.username}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Email</dt>
                <dd className="text-sm font-medium">{user.email}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Name</dt>
                <dd className="text-sm font-medium">
                  {user.first_name} {user.last_name}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Status</dt>
                <dd>
                  <Badge variant={user.is_active ? "default" : "secondary"}>
                    {user.is_active ? "active" : "inactive"}
                  </Badge>
                </dd>
              </div>
            </dl>
          ) : null}
          <form
            className="flex flex-wrap items-end gap-2 border-t pt-4"
            onSubmit={(event) => {
              event.preventDefault();
              saveProfile.mutate();
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="first-name" className="text-xs">
                First name
              </Label>
              <Input
                id="first-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                className="w-44"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="last-name" className="text-xs">
                Last name
              </Label>
              <Input
                id="last-name"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                className="w-44"
              />
            </div>
            <Button
              type="submit"
              size="sm"
              disabled={
                saveProfile.isPending ||
                !firstName.trim() ||
                !lastName.trim() ||
                (firstName === (user?.first_name ?? "") &&
                  lastName === (user?.last_name ?? ""))
              }
            >
              {saveProfile.isPending && (
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
              )}
              Save
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Choose how the console looks.</CardDescription>
        </CardHeader>
        <CardContent>
          <Label className="mb-2 block text-xs text-muted-foreground">
            Theme
          </Label>
          <div className="flex gap-2">
            {THEME_OPTIONS.map((option) => {
              const Icon = option.icon;
              const isActive = mounted && theme === option.value;

              return (
                <Button
                  key={option.value}
                  type="button"
                  variant={isActive ? "default" : "outline"}
                  size="sm"
                  disabled={!mounted}
                  onClick={() => setTheme(option.value)}
                  className={cn(!mounted && "opacity-50")}
                >
                  <Icon className="mr-2 h-4 w-4" />
                  {option.label}
                </Button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Organization</CardTitle>
          <CardDescription>
            Details for your organization. Changing these needs the
            organization.write permission.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {organization.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : organization.isError ? (
            <p className="text-sm text-muted-foreground">
              {(organization.error as ApiError)?.status === 403
                ? "You don't have permission to view organization settings."
                : "Organization details couldn't be loaded."}
            </p>
          ) : (
            <>
              <dl className="grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">Code</dt>
                  <dd className="text-sm font-medium">
                    {organization.data?.code}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Plan</dt>
                  <dd className="text-sm font-medium">
                    <Badge variant="outline">{organization.data?.plan}</Badge>
                  </dd>
                </div>
              </dl>

              <form
                className="flex flex-wrap items-end gap-2 border-t pt-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  saveOrganization.mutate();
                }}
              >
                <div className="space-y-1">
                  <Label htmlFor="org-name" className="text-xs">
                    Name
                  </Label>
                  <Input
                    id="org-name"
                    value={orgName}
                    onChange={(event) => setOrgName(event.target.value)}
                    className="w-64"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="org-domain" className="text-xs">
                    Domain (optional)
                  </Label>
                  <Input
                    id="org-domain"
                    value={orgDomain}
                    onChange={(event) => setOrgDomain(event.target.value)}
                    placeholder="acme.example"
                    className="w-64"
                  />
                </div>
                <Button
                  type="submit"
                  size="sm"
                  disabled={saveOrganization.isPending || !orgName.trim()}
                >
                  {saveOrganization.isPending && (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  )}
                  Save
                </Button>
              </form>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
