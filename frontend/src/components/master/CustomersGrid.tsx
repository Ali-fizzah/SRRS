"use client";

import type { GridColDef } from "@mui/x-data-grid";

import { SourceLink } from "@/components/master/MasterPage";
import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";

type Customer = Schemas["CustomerOut"];

const COLUMNS: GridColDef<Customer>[] = [
  { field: "customer_code", headerName: "Customer code", width: 200 },
  { field: "name", headerName: "Name", flex: 1, minWidth: 220 },
  { field: "country", headerName: "Country", width: 100 },
  {
    field: "source",
    headerName: "Source",
    width: 170,
    sortable: false,
    renderCell: ({ row }) => <SourceLink upload={row.source_upload_id} row={row.source_row} />,
  },
];

export default function CustomersGrid() {
  return (
    <ServerDataGrid<Customer>
      path="/customers"
      columns={COLUMNS}
      label="Customers"
      emptyText="No customers yet. Upload a customers file to add them."
    />
  );
}
