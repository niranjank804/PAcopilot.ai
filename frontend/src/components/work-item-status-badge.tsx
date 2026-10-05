import { Badge } from "@/components/ui/badge";
import { STATUS_LABEL, type WorkItemStatus } from "@/lib/team";

export function WorkItemStatusBadge({ status }: { status: WorkItemStatus }) {
  return (
    <Badge variant={status === "resolved" || status === "closed" ? "secondary" : "outline"}>
      {STATUS_LABEL[status]}
    </Badge>
  );
}
