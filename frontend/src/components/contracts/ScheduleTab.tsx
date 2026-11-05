"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";
import type { GridColDef } from "@mui/x-data-grid";

import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type ScheduleRow = Schemas["ScheduleLineOut"];

const COLUMNS: GridColDef<ScheduleRow>[] = [
  {
    field: "service_period",
    headerName: "Service period",
    width: 130,
    valueFormatter: (value: string) => formatPeriod(value),
  },
  {
    field: "amount",
    headerName: "Amount",
    width: 120,
    align: "right",
    headerAlign: "right",
    valueFormatter: (value: string) => formatMoney(value),
  },
  { field: "line_no", headerName: "Line", type: "number", width: 70 },
  { field: "product_code", headerName: "Product", flex: 1, minWidth: 180 },
  { field: "method", headerName: "Method", width: 170, sortable: false },
  { field: "status", headerName: "Status", width: 120 },
  {
    field: "posting_period",
    headerName: "Booked in",
    width: 190,
    valueFormatter: (value: string | null) => (value ? formatPeriod(value) : "Not yet"),
    renderCell: ({ row, formattedValue }) => (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, height: "100%" }}>
        {formattedValue}
        {row.is_catch_up && <Chip size="small" label="Catch-up" variant="outlined" />}
      </Box>
    ),
  },
];

/** Revenue schedule with the total computed by the server (plan §5.4, §9). */
export default function ScheduleTab({ id }: { id: string }) {
  return (
    <ServerDataGrid<ScheduleRow>
      path={`/contracts/${id}/schedule`}
      columns={COLUMNS}
      label="Revenue schedule"
      emptyText="No schedule yet. Use Run recognition on the Contracts page."
      renderSummary={(page) => (
        <Box
          data-testid="schedule-summary"
          sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", mb: 1 }}
        >
          <Typography sx={{ flexGrow: 1 }}>
            {page.total} schedule line{page.total === 1 ? "" : "s"}, total{" "}
            <strong>{formatMoney(page.total_amount as string)}</strong>
          </Typography>
          <Button
            variant="outlined"
            size="small"
            href={`/api/v1/contracts/${id}/schedule?format=csv`}
          >
            Export CSV
          </Button>
        </Box>
      )}
    />
  );
}
