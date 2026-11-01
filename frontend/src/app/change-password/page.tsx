"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import { ChangePasswordForm } from "@/components/change-password-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/lib/auth-context";

/** Where the app sends someone signed in with a temporary password from
 * the Super Admin: nothing else answers until they set their own. Outside
 * the app shell on purpose, so the shell's own redirect cannot loop. */
export default function ChangePasswordPage() {
  const router = useRouter();
  const { user, isLoading, isAuthenticated, adoptSession, logout } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || !user) {
    return null;
  }

  const temporary = Boolean(user.must_change_password);

  const onChanged = async (session: { access_token: string; refresh_token: string }) => {
    // The change ended every session, this one included, and returned a
    // fresh one: continue with it, no trip through the login page.
    try {
      await adoptSession(session);
      toast.success("Password set.");
      router.replace("/dashboard");
    } catch {
      logout();
      toast.success("Password set. Sign in with it.");
      router.replace("/login");
    }
  };

  return (
    <div className="flex flex-1 items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{temporary ? "Choose your password" : "Change password"}</CardTitle>
          <CardDescription>
            {temporary
              ? "Your administrator gave you a temporary password. Set one of your own to continue; the temporary one stops working now."
              : "Enter your current password and the new one. Your other sessions are signed out."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ChangePasswordForm
            currentLabel={temporary ? "Temporary password" : "Current password"}
            submitLabel={temporary ? "Set password and continue" : "Change password"}
            onChanged={onChanged}
          />
          {!temporary ? (
            <p className="text-center text-sm">
              <Link href="/dashboard" className="font-medium text-primary hover:underline">
                Back to the app
              </Link>
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
