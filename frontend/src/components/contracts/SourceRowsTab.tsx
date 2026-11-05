"use client";

import Link from "@mui/material/Link";
import type { GridColDef } from "@mui/x-data-grid";
import NextLink from "next/link";

import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";

type SourceRow = Schemas["SourceRowOut"];

const COLUMNS: GridColDef<SourceRow>[] = [
  { field: "record_type", headerName: "Record", width: 140 },
  {
    field: "filename",
    headerName: "File",
    width: 220,
    renderCell: ({ row }) => (
      <Link component={NextLink} href={`/uploads/${row.upload_id}`}>
        {row.filename}
      </Link>
    ),
  },
  { field: "source_row", headerName: "Row", type: "number", width: 70 },
  {
    field: "payload",
    headerName: "As uploaded",
    flex: 1,
    minWidth: 320,
    sortable: false,
    valueGetter: (_value, row) =>
      Object.entries(row.payload ?? {})
        .filter(([, cell]) => cell !== "")
        .map(([column, cell]) => `${column}: ${String(cell)}`)
        .join(", "),
  },
];

/** The uploaded rows behind this contract: the end point of the drill-down (plan §9). */
export default function SourceRowsTab({ id }: { id: string }) {
  return (
    <ServerDataGrid<SourceRow>
      path={`/contracts/${id}/source-rows`}
      columns={COLUMNS}
      label="Source rows"
      emptyText="No uploaded rows."
      wrapText
    />
  );
}
