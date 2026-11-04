"use client";

import type { GridColDef } from "@mui/x-data-grid";

import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";

type GlMapping = Schemas["GlMappingOut"];

const COLUMNS: GridColDef<GlMapping>[] = [
  { field: "account_role", headerName: "Account role", width: 190 },
  {
    // D12: product mapping first, then category, then the default.
    field: "scope",
    headerName: "Applies to",
    flex: 1,
    minWidth: 240,
    sortable: false,
    valueGetter: (_value, row) => {
      if (row.product_code) return `Product ${row.product_code}`;
      if (row.product_category) return `Category ${row.product_category}`;
      return "Default";
    },
  },
  { field: "account_code", headerName: "Account", width: 110 },
  { field: "account_name", headerName: "Account name", flex: 1, minWidth: 220, sortable: false },
];

export default function GlMappingsGrid() {
  return (
    <ServerDataGrid<GlMapping>
      path="/gl-mappings"
      columns={COLUMNS}
      label="GL mappings"
      emptyText="No GL mappings yet. Run make seed to add the defaults."
    />
  );
}
