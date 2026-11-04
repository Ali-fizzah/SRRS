"use client";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { GridColDef } from "@mui/x-data-grid";
import { useQuery } from "@tanstack/react-query";
import NextLink from "next/link";

import ServerDataGrid from "@/components/ServerDataGrid";
import StatusChip, { isFinal } from "@/components/uploads/StatusChip";
import { apiGet, type Schemas } from "@/lib/api/client";

type ValidationRow = Schemas["ValidationErrorOut"];

const COLUMNS: GridColDef<ValidationRow>[] = [
  { field: "row_number", headerName: "Row", type: "number", width: 80 },
  { field: "column_name", headerName: "Column", width: 170 },
  { field: "error_code", headerName: "Code", width: 90 },
  { field: "message", headerName: "What is wrong", flex: 1, minWidth: 300, sortable: false },
  { field: "raw_value", headerName: "Value in the file", width: 190, sortable: false },
];

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" component="div">
        {label}
      </Typography>
      <Typography variant="h2" component="div">
        {value}
      </Typography>
    </Box>
  );
}

/** Validation log for one upload, with CSV download (plan §9, §7.1). */
export default function UploadDetail({ id }: { id: string }) {
  const upload = useQuery({
    queryKey: ["/uploads", id],
    queryFn: () => apiGet<Schemas["UploadOut"]>(`/uploads/${id}`),
    refetchInterval: (q) => (q.state.data && !isFinal(q.state.data.status) ? 1500 : false),
  });
  const data = upload.data;

  return (
    <Stack spacing={2}>
      <Box>
        <Button component={NextLink} href="/uploads" startIcon={<ArrowBackIcon />} size="small">
          All uploads
        </Button>
      </Box>
      {upload.isError && <Alert severity="error">{upload.error.message}</Alert>}
      {upload.isPending && <Skeleton variant="rounded" height={120} />}
      {data && (
        <Card>
          <CardContent>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap", mb: 2 }}>
              <Typography variant="h1" sx={{ overflowWrap: "anywhere" }}>
                {data.original_filename}
              </Typography>
              <StatusChip status={data.status} />
            </Box>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
              {data.template} template · period {data.period_key} · uploaded by {data.uploaded_by}{" "}
              on {new Date(data.created_at).toLocaleString()}
            </Typography>
            <Stack direction="row" spacing={4} sx={{ mb: 2 }}>
              <Figure label="Rows" value={data.total_rows} />
              <Figure label="Accepted" value={data.accepted_rows} />
              <Figure label="Rejected" value={data.rejected_rows} />
            </Stack>
            <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
              <Button variant="contained" href={`/api/v1/uploads/${id}/errors?format=csv`}>
                Download error log (CSV)
              </Button>
              <Button variant="outlined" href={`/api/v1/uploads/${id}/file`}>
                Download original file
              </Button>
            </Box>
          </CardContent>
        </Card>
      )}
      {data && (
        <Box>
          <Typography variant="h2" sx={{ mb: 1 }}>
            Validation log
          </Typography>
          <ServerDataGrid<ValidationRow>
            path={`/uploads/${id}/errors`}
            columns={COLUMNS}
            label="Validation log"
            wrapText
            emptyText={
              isFinal(data.status)
                ? "No errors: every row was accepted."
                : "The file is still being checked."
            }
            refetchInterval={() => (isFinal(data.status) ? false : 1500)}
          />
        </Box>
      )}
    </Stack>
  );
}
