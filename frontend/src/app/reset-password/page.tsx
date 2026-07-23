"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

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
import { ApiError, apiRequest } from "@/lib/api-client";

const resetPasswordSchema = z
  .object({
    new_password: z.string().min(8, "At least 8 characters"),
    confirm_password: z.string(),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    message: "Passwords don't match",
    path: ["confirm_password"],
  });

type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
  });

  const onSubmit = async (values: ResetPasswordValues) => {
    if (!token) return;

    setIsSubmitting(true);

    try {
      await apiRequest<null>("/auth/reset-password", {
        method: "POST",
        body: { token, new_password: values.new_password },
        skipAuth: true,
      });
      toast.success("Password reset. Sign in with your new password.");
      router.push("/login");
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Something went wrong.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-xl">Set a new password</CardTitle>
        <CardDescription>Choose a new password for your account.</CardDescription>
      </CardHeader>
      <CardContent>
        {!token ? (
          <div className="space-y-4">
            <p className="text-sm text-destructive">
              This link is missing its reset token. Request a new one.
            </p>
            <Link
              href="/forgot-password"
              className="text-sm font-medium text-primary hover:underline"
            >
              Request a new reset link
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="new_password">New password</Label>
              <Input
                id="new_password"
                type="password"
                autoComplete="new-password"
                {...register("new_password")}
              />
              {errors.new_password ? (
                <p className="text-sm text-destructive">
                  {errors.new_password.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm_password">Confirm password</Label>
              <Input
                id="confirm_password"
                type="password"
                autoComplete="new-password"
                {...register("confirm_password")}
              />
              {errors.confirm_password ? (
                <p className="text-sm text-destructive">
                  {errors.confirm_password.message}
                </p>
              ) : null}
            </div>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? "Resetting..." : "Reset password"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-muted/40 p-4">
      <Suspense fallback={null}>
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}
