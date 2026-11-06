"use client";

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { Schemas } from "@/lib/api/client";

type Item = Schemas["ChecklistItemOut"];

const CHIP: Record<Item["status"], { label: string; color: "success" | "warning" | "error" }> = {
  pass: { label: "Pass", color: "success" },
  warn: { label: "Warning", color: "warning" },
  fail: { label: "Not yet", color: "error" },
};

/** The close checklist (plan §5.8), one row per item with what to do about it. */
export default function Checklist({ items }: { items: Item[] }) {
  return (
    <Stack
      spacing={1.5}
      component="ol"
      sx={{ listStyle: "none", m: 0, p: 0 }}
      aria-label="Close checklist"
    >
      {items.map((item) => (
        <Box
          component="li"
          key={item.id}
          data-testid={`checklist-${item.id}`}
          data-status={item.status}
          sx={{ display: "flex", gap: 1.5, alignItems: "flex-start" }}
        >
          <Chip
            size="small"
            label={CHIP[item.status].label}
            color={CHIP[item.status].color}
            sx={{ minWidth: 78 }}
          />
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 500 }}>{item.label}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
              {item.detail}
            </Typography>
          </Box>
        </Box>
      ))}
    </Stack>
  );
}
