"use client";

import Chip from "@mui/material/Chip";
import { useEffect, useState } from "react";

type Status = "checking" | "ok" | "down";

/** Shows whether /api reaches FastAPI through the Next.js rewrite (plan D11). */
export default function ApiHealth() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    fetch("/api/v1/health")
      .then((res) => setStatus(res.ok ? "ok" : "down"))
      .catch(() => setStatus("down"));
  }, []);

  const color = status === "ok" ? "success" : status === "down" ? "error" : "default";
  return <Chip label={`API: ${status}`} color={color} size="small" sx={{ mt: 2 }} />;
}
