import type { Metadata } from "next";

import { LegalPage, LegalValue } from "@/components/legal-page";
import { legalIdentity } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "The terms you agree to when using PA-Copilot.",
};

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service">
      <p>
        These terms govern your use of PA-Copilot, provided by{" "}
        <LegalValue
          value={legalIdentity.entity}
          envVar="NEXT_PUBLIC_LEGAL_ENTITY"
        />
        . By using the service you agree to them.
      </p>

      <h2>Accounts</h2>
      <p>
        You are responsible for keeping your credentials secure and for
        activity under your account. An administrator in your organization
        may grant, change or revoke your access at any time.
      </p>

      <h2>Acceptable use</h2>
      <ul>
        <li>
          Connect only to TM1 servers you are authorized to access. The
          service does not and cannot verify that authorization for you.
        </li>
        <li>
          Do not attempt to access another organization&rsquo;s data, or to
          circumvent the permission model.
        </li>
        <li>
          Do not upload material you do not have the right to share.
        </li>
      </ul>

      <h2>AI-generated output</h2>
      <p>
        The assistant drafts TurboIntegrator processes, rules and feeders,
        and answers questions about your model. This output is a
        suggestion, not a reviewed deliverable. It can be wrong, and it can
        be confidently wrong.
      </p>
      <p>
        <strong>
          You are responsible for reviewing anything the assistant produces
          before it reaches a production system.
        </strong>{" "}
        Changes to a TM1 server require your explicit approval by design,
        and that approval step is yours to exercise meaningfully — it is
        the control that stands between a generated draft and your data.
      </p>

      <h2>Availability</h2>
      <p>
        We aim to keep the service available but do not guarantee
        uninterrupted access. Maintenance, provider outages and faults can
        interrupt it. The service depends on third-party AI providers, and
        their availability limits ours.
      </p>

      <h2>Liability</h2>
      <p>
        The service is provided on an &ldquo;as is&rdquo; basis. To the
        extent permitted by law, we are not liable for indirect or
        consequential loss, including loss of data or profit arising from
        use of the service or of output it generates.
      </p>

      <h2>Termination</h2>
      <p>
        You may stop using the service at any time. We may suspend access
        for breach of these terms. If access ends, you keep the right to
        obtain a copy of your own data — losing write access never means
        losing access to your records.
      </p>

      <h2>Governing law</h2>
      <p>
        These terms are governed by the laws of{" "}
        <LegalValue
          value={legalIdentity.jurisdiction}
          envVar="NEXT_PUBLIC_LEGAL_JURISDICTION"
        />
        .
      </p>
    </LegalPage>
  );
}
