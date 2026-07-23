import type { ChangeStatus, ChangeType } from "@/lib/types";

export const STATUS_VARIANT: Record<
  ChangeStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  draft: "secondary",
  executed: "default",
  failed: "destructive",
  rolled_back: "outline",
};

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
