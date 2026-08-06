import type { ChangeStatus, ChangeType } from "@/lib/types";

export const STATUS_VARIANT: Record<
  ChangeStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  draft: "secondary",
  executed: "default",
  failed: "destructive",
  rolled_back: "outline",
  rejected: "outline",
  superseded: "outline",
};

/** What each status is called in the interface.
 *
 * A draft is shown as STET — the TM1 rule keyword for "leave this value
 * alone". It is the one state where the AI has finished and the server is
 * deliberately untouched, and naming it after the keyword says that to a TM1
 * developer without a sentence of explanation. Every other status keeps its
 * plain-English name; inventing vocabulary for states that already read
 * clearly would be branding at the user's expense.
 *
 * Defined once because the badge appears on five screens, and a status that
 * reads differently in two of them is worse than one that reads plainly in
 * all five.
 */
export const STATUS_LABEL: Record<ChangeStatus, string> = {
  draft: "STET",
  executed: "executed",
  failed: "failed",
  rolled_back: "rolled back",
  rejected: "discarded",
  superseded: "superseded",
};

export function statusLabel(status: ChangeStatus | string): string {
  return STATUS_LABEL[status as ChangeStatus] ?? status.replace("_", " ");
}

export const CHANGE_TYPE_LABEL: Record<ChangeType, string> = {
  update_rules: "Update rules",
  create_process: "Create process",
  update_process: "Update process",
  delete_process: "Delete process",
};

// Maps the short keys used in TM1Change.new_content to the PascalCase field
// names TM1py's Process.body_as_dict returns for the "current" side of a
// diff — the backend intentionally keeps these different (new_content is a
// clean API contract, body_as_dict is TM1py's own REST shape).
export const PROCESS_FIELD_MAP: Record<string, string> = {
  prolog: "PrologProcedure",
  metadata: "MetadataProcedure",
  data: "DataProcedure",
  epilog: "EpilogProcedure",
};
