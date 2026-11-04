import Chip from "@mui/material/Chip";

import type { Schemas } from "@/lib/api/client";

export type UploadStatus = Schemas["UploadStatus"];

const COLORS: Record<UploadStatus, "default" | "info" | "success" | "warning" | "error"> = {
  RECEIVED: "default",
  VALIDATING: "info",
  ACCEPTED: "success",
  PARTIAL: "warning",
  REJECTED: "error",
};

/** RECEIVED and VALIDATING are still in progress; the others are final (plan §5.8). */
export function isFinal(status: UploadStatus): boolean {
  return status === "ACCEPTED" || status === "PARTIAL" || status === "REJECTED";
}

export default function StatusChip({ status }: { status: UploadStatus }) {
  return <Chip label={status} color={COLORS[status]} size="small" />;
}
