"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiRequest } from "@/lib/api-client";

const schema = z
  .object({
    current_password: z.string().min(1, "Enter your current password"),
    new_password: z.string().min(8, "At least 8 characters"),
    confirm_password: z.string(),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    message: "Passwords don't match",
    path: ["confirm_password"],
  });

type Values = z.infer<typeof schema>;

interface ChangePasswordFormProps {
  /** What the current password is called on screen: "Temporary password"
   * for someone the Super Admin let in, "Current password" otherwise. */
  currentLabel?: string;
  submitLabel?: string;
  /** The server accepted the new password. Every session ended with the
   * change, this one included; `session` is the fresh one it returned. */
  onChanged: (session: { access_token: string; refresh_token: string }) => Promise<void> | void;
}

/** Shared by the forced change after a temporary password and by
 * Settings: one place that knows the endpoint and its rules. */
export function ChangePasswordForm({
  currentLabel = "Current password",
  submitLabel = "Change password",
  onChanged,
}: ChangePasswordFormProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: Values) => {
    setIsSubmitting(true);
    try {
      const session = await apiRequest<{ access_token: string; refresh_token: string }>(
        "/auth/change-password",
        {
          method: "POST",
          body: { current_password: values.current_password, new_password: values.new_password },
        },
      );
      reset();
      await onChanged(session);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="current_password">{currentLabel}</Label>
        <Input
          id="current_password"
          type="password"
          autoComplete="current-password"
          {...register("current_password")}
        />
        {errors.current_password ? (
          <p className="text-sm text-destructive">{errors.current_password.message}</p>
        ) : null}
      </div>
      <div className="space-y-2">
        <Label htmlFor="new_password">New password</Label>
        <Input id="new_password" type="password" autoComplete="new-password" {...register("new_password")} />
        {errors.new_password ? (
          <p className="text-sm text-destructive">{errors.new_password.message}</p>
        ) : null}
      </div>
      <div className="space-y-2">
        <Label htmlFor="confirm_password">Confirm new password</Label>
        <Input
          id="confirm_password"
          type="password"
          autoComplete="new-password"
          {...register("confirm_password")}
        />
        {errors.confirm_password ? (
          <p className="text-sm text-destructive">{errors.confirm_password.message}</p>
        ) : null}
      </div>
      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? "Saving..." : submitLabel}
      </Button>
    </form>
  );
}
