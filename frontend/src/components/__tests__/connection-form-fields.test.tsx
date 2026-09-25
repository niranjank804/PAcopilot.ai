/**
 * The PA SaaS address guard.
 *
 * A real connection was saved as "native" with the SaaS hostname and port
 * 8010, and could never connect. The form now says so while the address
 * is being typed, instead of after a failed test.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import {
  ConnectionFormFields,
  databaseFromBaseUrl,
  looksLikeSaasAddress,
  type ConnectionFormValues,
} from "../connection-form-fields";

function Harness({
  authType,
}: {
  authType: "native" | "v12_saas" | "pa_cloud";
}) {
  const { register, control, formState } = useForm<ConnectionFormValues>({
    defaultValues: { authentication_type: authType, port: 8010, ssl: true },
  });

  return (
    <ConnectionFormFields
      register={register}
      control={control}
      errors={formState.errors}
      authType={authType}
      passwordLabel="Password"
    />
  );
}

describe("looksLikeSaasAddress", () => {
  it("recognises the address the way it is usually pasted", () => {
    expect(
      looksLikeSaasAddress("us-east-1.planninganalytics.saas.ibm.com/"),
    ).toBe(true);
    expect(
      looksLikeSaasAddress("https://eu-central-1.planninganalytics.saas.ibm.com"),
    ).toBe(true);
  });

  it("leaves on-prem servers and lookalikes alone", () => {
    expect(looksLikeSaasAddress("tm1.example.com")).toBe(false);
    expect(
      looksLikeSaasAddress("x.planninganalytics.saas.ibm.com.evil.example"),
    ).toBe(false);
    expect(looksLikeSaasAddress(undefined)).toBe(false);
  });
});

describe("databaseFromBaseUrl", () => {
  it("reads the database from a TM1 base URL as an .env holds it", () => {
    expect(
      databaseFromBaseUrl(
        "https://assurantdev.planning-analytics.ibmcloud.com/tm1/api/AssurantGFSDev",
      ),
    ).toBe("AssurantGFSDev");
    expect(
      databaseFromBaseUrl(
        "https://x.planning-analytics.ibmcloud.com/tm1/api/Planning%20Sample/api/v1/",
      ),
    ).toBe("Planning Sample");
  });

  it("returns nothing for a bare hostname", () => {
    expect(databaseFromBaseUrl("x.planning-analytics.ibmcloud.com")).toBeNull();
    expect(databaseFromBaseUrl(undefined)).toBeNull();
  });
});

describe("ConnectionFormFields", () => {
  it("warns when a SaaS address is typed under the native type", async () => {
    render(<Harness authType="native" />);

    expect(screen.queryByRole("alert")).toBeNull();

    await userEvent.type(
      screen.getByLabelText("Address"),
      "us-east-1.planninganalytics.saas.ibm.com/",
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Planning Analytics as a Service",
    );
  });

  it("asks a PA on Cloud connection for the non-interactive account and database", () => {
    render(<Harness authType="pa_cloud" />);

    expect(screen.getByLabelText("TM1 base URL or hostname")).toBeInTheDocument();
    expect(screen.getByLabelText("Service account")).toBeInTheDocument();
    expect(screen.getByLabelText("Database")).toBeInTheDocument();
    // IBM's gateway is HTTPS on 443: neither is the user's to choose.
    expect(screen.queryByLabelText("Port")).toBeNull();
    expect(screen.queryByLabelText("Use SSL")).toBeNull();
  });

  it("does not carry the port into the Tenant ID when the type changes", () => {
    // The screenshot bug: native opens with port 8010; switching to PA as a
    // Service showed 8010 in Tenant ID, and it was saved as the tenant.
    const { rerender } = render(<Harness authType="native" />);
    expect(screen.getByLabelText("Port")).toHaveValue(8010);

    rerender(<Harness authType="v12_saas" />);

    expect(screen.getByLabelText("Tenant ID")).toHaveValue("");
    expect(screen.getByLabelText("Database")).toHaveValue("");
  });

  it("does not warn once the SaaS type is chosen", async () => {
    render(<Harness authType="v12_saas" />);

    await userEvent.type(
      screen.getByLabelText("PA SaaS hostname"),
      "us-east-1.planninganalytics.saas.ibm.com",
    );

    expect(screen.queryByRole("alert")).toBeNull();
  });
});
