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
  looksLikeSaasAddress,
  type ConnectionFormValues,
} from "../connection-form-fields";

function Harness({ authType }: { authType: "native" | "v12_saas" }) {
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

  it("does not warn once the SaaS type is chosen", async () => {
    render(<Harness authType="v12_saas" />);

    await userEvent.type(
      screen.getByLabelText("PA SaaS hostname"),
      "us-east-1.planninganalytics.saas.ibm.com",
    );

    expect(screen.queryByRole("alert")).toBeNull();
  });
});
