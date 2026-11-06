"use client";

import PrintIcon from "@mui/icons-material/Print";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import GlobalStyles from "@mui/material/GlobalStyles";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useSearchParams } from "next/navigation";
import { type ReactNode, Suspense, useEffect, useMemo, useState } from "react";

export type ReportFilters = Record<string, string | undefined>;
type FilterName = "period" | "customer" | "contract" | "product" | "account";

const TEXT_FILTERS: { name: Exclude<FilterName, "period">; label: string }[] = [
  { name: "customer", label: "Customer" },
  { name: "contract", label: "Contract" },
  { name: "product", label: "Product" },
  { name: "account", label: "Account" },
];

const PRINT_STYLES = {
  "@media print": {
    ".MuiAppBar-root, .MuiDrawer-root, .no-print, .MuiDataGrid-footerContainer": {
      display: "none !important",
    },
    "main, body": { margin: "0 !important", padding: "0 !important", width: "100% !important" },
    ".MuiDataGrid-root": { border: "none" },
  },
};

const toMonth = (key: string | null) => (key ? `${key.slice(0, 4)}-${key.slice(4)}` : "");
const toKey = (month: string) => month.replace("-", "") || undefined;

function Frame({
  title,
  subtitle,
  path,
  filters: shown,
  children,
}: {
  title: string;
  subtitle: string;
  path: string;
  filters: FilterName[];
  children: (filters: ReportFilters) => ReactNode;
}) {
  const url = useSearchParams();
  // Text waits for a pause in typing; period pickers and links from other reports apply at once.
  const [from, setFrom] = useState(toMonth(url.get("period_from")));
  const [to, setTo] = useState(toMonth(url.get("period_to")));
  const [draft, setDraft] = useState<Record<string, string>>({
    customer: url.get("customer") ?? "",
    contract: url.get("contract") ?? "",
    product: url.get("product") ?? "",
    account: url.get("account") ?? "",
  });
  const [applied, setApplied] = useState(draft);
  useEffect(() => {
    const timer = setTimeout(() => setApplied(draft), 300);
    return () => clearTimeout(timer);
  }, [draft]);

  const groupBy = url.get("group_by") ?? undefined;
  const filters = useMemo<ReportFilters>(() => {
    const values: ReportFilters = { period_from: toKey(from), period_to: toKey(to) };
    if (groupBy) values.group_by = groupBy;
    for (const [name, value] of Object.entries(applied)) {
      if (value.trim()) values[name] = value.trim();
    }
    return values;
  }, [from, to, applied, groupBy]);

  const csv = new URLSearchParams({ format: "csv" });
  for (const [name, value] of Object.entries(filters)) {
    if (value) csv.set(name, value);
  }

  return (
    <Stack spacing={2}>
      <GlobalStyles styles={PRINT_STYLES} />
      <Box>
        <Typography variant="h1" gutterBottom>
          {title}
        </Typography>
        <Typography color="text.secondary">{subtitle}</Typography>
      </Box>
      <Box
        className="no-print"
        sx={{ display: "flex", gap: 1.5, flexWrap: "wrap", alignItems: "center" }}
      >
        {shown.includes("period") && (
          <>
            <TextField
              label="From"
              type="month"
              size="small"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="To"
              type="month"
              size="small"
              value={to}
              onChange={(event) => setTo(event.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </>
        )}
        {TEXT_FILTERS.filter(({ name }) => shown.includes(name)).map(({ name, label }) => (
          <TextField
            key={name}
            label={label}
            size="small"
            value={draft[name]}
            onChange={(event) => setDraft({ ...draft, [name]: event.target.value })}
            sx={{ width: 170 }}
          />
        ))}
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="outlined" size="small" href={`/api/v1${path}?${csv}`}>
          Export CSV
        </Button>
        <Button
          variant="outlined"
          size="small"
          startIcon={<PrintIcon />}
          onClick={() => window.print()}
        >
          Print
        </Button>
      </Box>
      {children(filters)}
    </Stack>
  );
}

/** Filter bar, Export CSV and Print for every report (plan §9). Filters can come from the URL. */
export default function ReportFrame(props: {
  title: string;
  subtitle: string;
  path: string;
  filters: FilterName[];
  children: (filters: ReportFilters) => ReactNode;
}) {
  return (
    <Suspense>
      <Frame {...props} />
    </Suspense>
  );
}
