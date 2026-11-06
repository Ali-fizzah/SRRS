"use client";

import Chip from "@mui/material/Chip";
import type { GridColDef } from "@mui/x-data-grid";

import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";

type GlAccount = Schemas["GlAccountOut"];

const COLUMNS: GridColDef<GlAccount>[] = [
  { field: "account_code", headerName: "Code", width: 110 },
  { field: "name", headerName: "Name", flex: 1, minWidth: 260 },
  { field: "type", headerName: "Type", width: 130 },
  {
    field: "is_active",
    headerName: "Status",
    width: 110,
    renderCell: ({ row }) => (
      <Chip
        size="small"
        label={row.is_active ? "Active" : "Inactive"}
        color={row.is_active ? "success" : "default"}
      />
    ),
  },
];

export default function GlAccountsGrid() {
  return (
    <ServerDataGrid<GlAccount>
      path="/gl-accounts"
      columns={COLUMNS}
      label="GL accounts"
      emptyText="No GL accounts yet. Run make seed to add the default chart of accounts."
    />
  );
}
