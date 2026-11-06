"use client";

import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";
import type { GridColDef } from "@mui/x-data-grid";
import NextLink from "next/link";

import ServerDataGrid from "@/components/ServerDataGrid";
import StatusChip, { isFinal } from "@/components/uploads/StatusChip";
import type { Schemas } from "@/lib/api/client";

type Upload = Schemas["UploadOut"];

const COLUMNS: GridColDef<Upload>[] = [
  {
    field: "original_filename",
    headerName: "File",
    flex: 1,
    minWidth: 200,
    renderCell: ({ row }) => (
      <Link component={NextLink} href={`/uploads/${row.id}`}>
        {row.original_filename}
      </Link>
    ),
  },
  { field: "template", headerName: "Template", width: 130 },
  { field: "period_key", headerName: "Period", width: 90 },
  {
    field: "status",
    headerName: "Status",
    width: 120,
    renderCell: ({ row }) => <StatusChip status={row.status} />,
  },
  { field: "total_rows", headerName: "Rows", type: "number", width: 80 },
  { field: "accepted_rows", headerName: "Accepted", type: "number", width: 100 },
  { field: "rejected_rows", headerName: "Rejected", type: "number", width: 100 },
  { field: "uploaded_by", headerName: "Uploaded by", width: 150 },
  {
    field: "created_at",
    headerName: "Uploaded",
    width: 200,
    valueFormatter: (value: string) => new Date(value).toLocaleString(),
  },
];

export default function UploadHistory() {
  return (
    <>
      <Typography variant="h2" sx={{ mb: 1 }}>
        Upload history
      </Typography>
      <ServerDataGrid<Upload>
        path="/uploads"
        columns={COLUMNS}
        label="Upload history"
        emptyText="No files have been uploaded yet."
        refetchInterval={(rows) => (rows.some((row) => !isFinal(row.status)) ? 1500 : false)}
      />
    </>
  );
}
