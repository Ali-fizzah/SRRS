"use client";

import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import TextField from "@mui/material/TextField";
import type { GridColDef } from "@mui/x-data-grid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import ServerDataGrid from "@/components/ServerDataGrid";
import { apiGet, apiPost, type Schemas } from "@/lib/api/client";
import { formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

type Period = Schemas["PeriodOut"];

const COLORS: Record<Period["status"], "default" | "info" | "success" | "warning"> = {
  FUTURE: "default",
  OPEN: "success",
  CLOSING: "warning",
  CLOSED: "info",
};

/** All periods; an Admin can reopen the latest closed one, with a reason (plan §5.8). */
export default function PeriodsGrid() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const isAdmin = me.data?.roles.includes("ADMIN") ?? false;
  const latest = useQuery({
    queryKey: ["/periods", "latest-closed"],
    queryFn: () =>
      apiGet<{ items: Period[] }>("/periods", {
        status: "CLOSED",
        sort: "-period_key",
        page_size: 1,
      }),
    enabled: isAdmin,
  });
  const latestKey = latest.data?.items[0]?.period_key;
  const [reopening, setReopening] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const reopen = useMutation({
    mutationFn: ({ key, text }: { key: string; text: string }) =>
      apiPost<Period>(`/periods/${key}/reopen`, { reason: text }),
    onSuccess: async () => {
      setReopening(null);
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["/periods"] });
    },
  });

  const columns = useMemo<GridColDef<Period>[]>(
    () => [
      {
        field: "period_key",
        headerName: "Period",
        width: 120,
        valueFormatter: (value: string) => formatPeriod(value),
      },
      { field: "start_date", headerName: "Start", width: 120, sortable: false },
      { field: "end_date", headerName: "End", width: 120, sortable: false },
      {
        field: "status",
        headerName: "Status",
        width: 130,
        renderCell: ({ row }) => (
          <Chip size="small" label={row.status} color={COLORS[row.status]} />
        ),
      },
      {
        field: "actions",
        headerName: "",
        flex: 1,
        minWidth: 110,
        sortable: false,
        renderCell: ({ row }) =>
          isAdmin && row.period_key === latestKey ? (
            <Button size="small" onClick={() => setReopening(row.period_key)}>
              Reopen
            </Button>
          ) : null,
      },
    ],
    [isAdmin, latestKey],
  );

  return (
    <>
      <ServerDataGrid<Period>
        path="/periods"
        columns={columns}
        label="Accounting periods"
        emptyText="No periods yet. Run make seed."
      />
      <Dialog open={reopening !== null} onClose={() => setReopening(null)} fullWidth maxWidth="sm">
        {reopening && (
          <>
            <DialogTitle>Reopen {formatPeriod(reopening)}?</DialogTitle>
            <DialogContent>
              <DialogContentText>
                It becomes the current period again and the next period goes back to future. This is
                refused if the next period already has a posted batch.
              </DialogContentText>
              <TextField
                label="Reason"
                required
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                fullWidth
                margin="normal"
                slotProps={{ htmlInput: { maxLength: 1000 } }}
              />
              {reopen.isError && <Alert severity="error">{reopen.error.message}</Alert>}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setReopening(null)}>Cancel</Button>
              <Button
                variant="contained"
                disabled={reopen.isPending || reason.trim().length < 3}
                onClick={() => reopen.mutate({ key: reopening, text: reason.trim() })}
              >
                Reopen
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </>
  );
}
