"use client";

import {
  Controller,
  type Control,
  type FieldErrors,
  type FieldValues,
  type Path,
  type UseFormRegister,
} from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface ConnectionFormValues {
  name: string;
  authentication_type: "native" | "v12_saas";
  address: string;
  port: number;
  ssl: boolean;
  username?: string;
  password?: string;
  tenant?: string;
  database?: string;
}

interface ConnectionFormFieldsProps<T extends FieldValues> {
  register: UseFormRegister<T>;
  control: Control<T>;
  errors: FieldErrors<T>;
  authType: "native" | "v12_saas";
  passwordLabel: string;
  passwordPlaceholder?: string;
}

// Shared by the "New Connection" and "Edit Connection" dialogs so the two
// forms can never drift out of sync with each other. Generic over T rather
// than fixed to one values type — the create form's password is required
// and the edit form's is optional, and UseFormRegister<T> is invariant in T,
// so a single non-generic prop type can't accept both callers' registers.
export function ConnectionFormFields<T extends FieldValues>({
  register,
  control,
  errors,
  authType,
  passwordLabel,
  passwordPlaceholder,
}: ConnectionFormFieldsProps<T>) {
  return (
    <>
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          placeholder="Production"
          {...register("name" as Path<T>)}
        />
        {errors.name ? (
          <p className="text-sm text-destructive">
            {String(errors.name.message)}
          </p>
        ) : null}
      </div>

      <div className="space-y-2">
        <Label htmlFor="authentication_type">Connection type</Label>
        <Controller
          control={control}
          name={"authentication_type" as Path<T>}
          render={({ field }) => (
            <Select value={field.value} onValueChange={field.onChange}>
              <SelectTrigger id="authentication_type" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="native">
                  Native (on-prem / self-hosted TM1)
                </SelectItem>
                <SelectItem value="v12_saas">
                  Planning Analytics as a Service (IBM Cloud API key)
                </SelectItem>
              </SelectContent>
            </Select>
          )}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="address">
          {authType === "v12_saas" ? "PA SaaS hostname" : "Address"}
        </Label>
        <Input
          id="address"
          placeholder={
            authType === "v12_saas"
              ? "us-east-1.planninganalytics.saas.ibm.com"
              : "tm1.example.com"
          }
          {...register("address" as Path<T>)}
        />
        {errors.address ? (
          <p className="text-sm text-destructive">
            {String(errors.address.message)}
          </p>
        ) : null}
        {authType === "v12_saas" ? (
          <p className="text-xs text-muted-foreground">
            Hostname only — no https:// prefix. Found in your PA workspace
            URL.
          </p>
        ) : null}
      </div>

      {authType === "v12_saas" ? (
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="tenant">Tenant</Label>
            <Input
              id="tenant"
              placeholder="2CX4TZWY5PSX"
              {...register("tenant" as Path<T>)}
            />
            {errors.tenant ? (
              <p className="text-sm text-destructive">
                {String(errors.tenant.message)}
              </p>
            ) : null}
          </div>
          <div className="space-y-2">
            <Label htmlFor="database">Database</Label>
            <Input
              id="database"
              placeholder="BusinessFlow"
              {...register("database" as Path<T>)}
            />
            {errors.database ? (
              <p className="text-sm text-destructive">
                {String(errors.database.message)}
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2 space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input id="username" {...register("username" as Path<T>)} />
            {errors.username ? (
              <p className="text-sm text-destructive">
                {String(errors.username.message)}
              </p>
            ) : null}
          </div>
          <div className="space-y-2">
            <Label htmlFor="port">Port</Label>
            <Input
              id="port"
              type="number"
              {...register("port" as Path<T>, { valueAsNumber: true })}
            />
            {errors.port ? (
              <p className="text-sm text-destructive">
                {String(errors.port.message)}
              </p>
            ) : null}
          </div>
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="password">{passwordLabel}</Label>
        <Input
          id="password"
          type="password"
          placeholder={passwordPlaceholder}
          {...register("password" as Path<T>)}
        />
        {errors.password ? (
          <p className="text-sm text-destructive">
            {String(errors.password.message)}
          </p>
        ) : null}
      </div>

      {authType === "native" ? (
        <div className="flex items-center gap-2">
          <input
            id="ssl"
            type="checkbox"
            className="h-4 w-4 accent-primary"
            {...register("ssl" as Path<T>)}
          />
          <Label htmlFor="ssl">Use SSL</Label>
        </div>
      ) : null}
    </>
  );
}
