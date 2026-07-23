"use client";

import { Monitor, Moon, Sun } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const THEME_OPTIONS = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

export default function SettingsPage() {
  const { user, isLoading } = useAuth();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Theme isn't known until after hydration — same pattern as ThemeToggle.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

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
          <p className="text-xs text-muted-foreground">
            Editing profile details isn&apos;t available yet — this needs a
            new backend endpoint that hasn&apos;t been built.
          </p>
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
            Organization-level settings aren&apos;t available yet — there is
            no backend endpoint to read or edit organization details today.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
