"use client";

import {
  Controller,
  useWatch,
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

// Every PA as a Service region is a subdomain of this. Mirrors
// backend/src/tm1/addressing.py, which refuses the same mistake on save.
const SAAS_HOST = /\.planninganalytics\.saas\.ibm\.com(?:[:/]|$)/i;

export function looksLikeSaasAddress(address: string | undefined): boolean {
  return SAAS_HOST.test((address ?? "").trim());
}

const AUTH_TYPE_LABEL: Record<string, string> = {
  native: "Native (on-prem / self-hosted TM1)",
  v12_saas: "Planning Analytics as a Service (IBM Cloud API key)",
};

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
  const address = useWatch({ control, name: "address" as Path<T> }) as
    | string
    | undefined;
  const saasAddressOnNativeType =
    authType === "native" && looksLikeSaasAddress(address);

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
                <SelectValue>
                  {(value: string) =>
                    AUTH_TYPE_LABEL[value] ?? "Select authentication type"
                  }
                </SelectValue>
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
            Hostname from your Planning Analytics URL. A pasted https:// or
            trailing slash is removed for you.
          </p>
        ) : null}
        {saasAddressOnNativeType ? (
          <p role="alert" className="text-sm text-destructive">
            This is a Planning Analytics as a Service address. Set Connection
            type to &ldquo;Planning Analytics as a Service&rdquo; and enter
            your tenant ID and database name — a port and username will not
            connect.
          </p>
        ) : null}
      </div>

      {authType === "v12_saas" ? (
        <div className="grid grid-cols-2 gap-4">
          <p className="col-span-2 text-xs text-muted-foreground">
            Tenant is your IBM tenant ID, a code like 2CX4TZWY5PSX — not the
            connection name. Database is the Planning Analytics database
            name — not a port number.
          </p>
          <div className="space-y-2">
            <Label htmlFor="tenant">Tenant ID</Label>
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
