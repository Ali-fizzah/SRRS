import Chip from "@mui/material/Chip";

import type { Schemas } from "@/lib/api/client";

type BatchStatus = Schemas["BatchStatus"];

const COLORS: Record<BatchStatus, "default" | "info" | "success"> = {
  DRAFT: "default",
  APPROVED: "info",
  POSTED: "success",
};

/** Plan §5.7: DRAFT -> APPROVED -> POSTED. */
export default function BatchStatusChip({ status }: { status: BatchStatus }) {
  return <Chip label={status} color={COLORS[status]} size="small" />;
}
