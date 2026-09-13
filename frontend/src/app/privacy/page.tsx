import type { Metadata } from "next";

import { LegalPage, LegalValue } from "@/components/legal-page";
import { legalIdentity } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "How PA-Copilot handles your data.",
};

/**
 * The data flows described here are taken from the implementation, not
 * from a template: message content going to Anthropic, document text
 * going to OpenAI for embeddings, and TM1 credentials held encrypted.
 * If any of those change, this page has to change with them.
 */
export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy">
      <p>
        This policy describes how{" "}
        <LegalValue
          value={legalIdentity.entity}
          envVar="NEXT_PUBLIC_LEGAL_ENTITY"
        />{" "}
        (&ldquo;we&rdquo;) handles information in PA-Copilot.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>
          <strong>Account details</strong> — your name, email address, the
          organization you belong to, and your assigned roles.
        </li>
        <li>
          <strong>TM1 connection details</strong> — server addresses and
          credentials. Credentials are encrypted at rest and are never
          returned by any API response, including to you.
        </li>
        <li>
          <strong>Conversations</strong> — the messages you exchange with
          the assistant, the tools it invoked, and token usage per request.
        </li>
        <li>
          <strong>Knowledge base documents</strong> — files you upload, and
          the text extracted from them for search.
        </li>
        <li>
          <strong>Audit records</strong> — significant actions, such as
          deploying a change to a TM1 server.
        </li>
      </ul>

      <h2>Who else processes it</h2>
      <p>
        Using the assistant necessarily sends data to third parties. We do
        not sell data to anyone, and these are the only processors
        involved:
      </p>
      <ul>
        <li>
          <strong>Anthropic</strong> — receives your messages, the relevant
          TM1 metadata, and knowledge-base excerpts, in order to generate
          replies.
        </li>
        <li>
          <strong>OpenAI</strong> — receives knowledge-base document text
          to produce the embeddings that make search work.
        </li>
        <li>
          <strong>Our hosting and database providers</strong> — store the
          data described above on our behalf.
        </li>
      </ul>
      <p>
        Your TM1 credentials are <strong>never</strong> sent to any AI
        provider. They are used only to connect to the servers you
        configure.
      </p>

      <h2>Retention</h2>
      <p>
        Data is retained while your account is active. Deleting a
        conversation, document or connection removes it from the
        application. Backups are kept for a limited period and expire on
        their own schedule.
      </p>

      <h2>Your rights</h2>
      <p>
        You can request a copy of your data, ask for corrections, or ask
        for deletion, by contacting us at{" "}
        <LegalValue
          value={legalIdentity.email}
          envVar="NEXT_PUBLIC_LEGAL_EMAIL"
        />
        . An administrator in your organization can also see and manage the
        accounts within it.
      </p>

      <h2>Contact</h2>
      <p>
        <LegalValue
          value={legalIdentity.entity}
          envVar="NEXT_PUBLIC_LEGAL_ENTITY"
        />
        <br />
        <LegalValue
          value={legalIdentity.address}
          envVar="NEXT_PUBLIC_LEGAL_ADDRESS"
        />
      </p>
    </LegalPage>
  );
}
