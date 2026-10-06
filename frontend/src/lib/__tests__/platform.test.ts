import { describe, expect, it } from "vitest";

import { auditCsv, type AuditRow } from "../platform";

const row = (over: Partial<AuditRow>): AuditRow => ({
  id: "1", at: "2026-10-06T10:00:00Z", action: "deactivate_user", entity: "User",
  entity_id: null, connection: null, user: null, organization: "Acme",
  details: {}, ip_address: "203.0.113.5", user_agent: null, ...over,
});

describe("auditCsv", () => {
  it("never lets a cell run as a spreadsheet formula", () => {
    const csv = auditCsv([
      row({ user: { id: "u", name: '=HYPERLINK("http://x","y")', email: "+cmd@x" }, details: { reason: "@SUM(1)" } }),
    ]);
    const cells = csv.split("\r\n")[1];
    expect(cells).not.toMatch(/(^|,)"?[=+@]/);
    expect(cells).toContain(`"'=HYPERLINK(""http://x"",""y"")"`);
    expect(cells).toContain("'+cmd@x");
  });
});
