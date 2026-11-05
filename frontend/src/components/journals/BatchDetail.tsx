"use client";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import type { GridColDef } from "@mui/x-data-grid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import BatchStatusChip from "@/components/journals/BatchStatusChip";
import ServerDataGrid from "@/components/ServerDataGrid";
import { apiGet, apiPost, type Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

type Detail = Schemas["JournalBatchDetail"];
type Line = Schemas["JournalLineOut"];
type Action = "approve" | "send-back" | "post";

const MAY_APPROVE = new Set(["APPROVER", "ADMIN"]); // plan §8: approve/post APPROVER
const MAY_REVERSE = new Set(["ACCOUNTANT", "APPROVER", "ADMIN"]);

const CONFIRM: Record<Action, { title: string; text: string; button: string }> = {
  approve: {
    title: "Approve this batch?",
    text: "It can then be posted. An approver can still send it back.",
    button: "Approve",
  },
  "send-back": {
    title: "Send this batch back?",
    text: "It returns to DRAFT, where generating journals again rebuilds it.",
    button: "Send back",
  },
  post: {
    title: "Post this batch?",
    text: "Posted entries can never be changed. Any correction is a new reversal entry.",
    button: "Post",
  },
};

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" component="div">
        {label}
      </Typography>
      <Typography component="div" sx={{ fontWeight: 500 }}>
        {value}
      </Typography>
    </Box>
  );
}

/** One batch: entries and lines, balance check, lifecycle and reversal (plan §5.7, §9). */
export default function BatchDetail({ id }: { id: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const path = `/journal-batches/${id}`;
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const detail = useQuery({
    queryKey: [path, "header"],
    queryFn: () => apiGet<Detail>(path, { page_size: 1 }),
  });

  const [pending, setPending] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [reversing, setReversing] = useState<Line | null>(null);
  const [reversalReason, setReversalReason] = useState("");

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: [path] }),
      queryClient.invalidateQueries({ queryKey: ["/journal-batches"] }),
    ]);

  const lifecycle = useMutation({
    mutationFn: (action: Action) =>
      apiPost<Schemas["JournalBatchOut"]>(
        `${path}/${action}`,
        action === "send-back" ? { reason: reason || null } : undefined,
      ),
    onSuccess: async () => {
      setPending(null);
      setReason("");
      await refresh();
    },
    onError: () => setPending(null),
  });

  const reverse = useMutation({
    mutationFn: ({ entryId, text }: { entryId: number; text: string }) =>
      apiPost<Schemas["ReverseOut"]>(`/journal-entries/${entryId}/reverse`, { reason: text }),
    onSuccess: async (result) => {
      setReversing(null);
      setReversalReason("");
      await refresh();
      router.push(`/journals/${result.batch_id}`);
    },
  });

  const roles = me.data?.roles ?? [];
  const canApprove = roles.some((role) => MAY_APPROVE.has(role));
  const canReverse = roles.some((role) => MAY_REVERSE.has(role));

  const columns = useMemo<GridColDef<Line>[]>(
    () => [
      { field: "entry_id", headerName: "Entry", type: "number", width: 80 },
      { field: "entry_type", headerName: "Type", width: 170 },
      { field: "entry_date", headerName: "Date", width: 110 },
      {
        field: "contract_code",
        headerName: "Contract",
        flex: 1,
        minWidth: 170,
        renderCell: ({ row }) => (
          <Link component={NextLink} href={`/contracts/${row.contract_id}`}>
            {row.contract_code}
          </Link>
        ),
      },
      {
        field: "account_code",
        headerName: "Account",
        flex: 1,
        minWidth: 200,
        valueGetter: (_value, row) => `${row.account_code} ${row.account_name}`,
      },
      { field: "line_no", headerName: "Line", type: "number", width: 70, sortable: false },
      {
        field: "debit",
        headerName: "Debit",
        width: 120,
        align: "right",
        headerAlign: "right",
        valueFormatter: (value: string) => (Number(value) === 0 ? "" : formatMoney(value)),
      },
      {
        field: "credit",
        headerName: "Credit",
        width: 120,
        align: "right",
        headerAlign: "right",
        valueFormatter: (value: string) => (Number(value) === 0 ? "" : formatMoney(value)),
      },
      {
        field: "actions",
        headerName: "",
        width: 110,
        sortable: false,
        renderCell: ({ row }) =>
          canReverse && row.first_of_entry && row.can_reverse ? (
            <Button size="small" onClick={() => setReversing(row)}>
              Reverse
            </Button>
          ) : null,
      },
    ],
    [canReverse],
  );

  const data = detail.data;
  const batch = data?.batch;
  const generatedByMe = batch !== undefined && me.data?.id === batch.generated_by_id;

  return (
    <Stack spacing={2}>
      <Box>
        <Button component={NextLink} href="/journals" startIcon={<ArrowBackIcon />} size="small">
          All batches
        </Button>
      </Box>
      {detail.isError && <Alert severity="error">{detail.error.message}</Alert>}
      {detail.isPending && <Skeleton variant="rounded" height={140} />}
      {batch && data && (
        <Card>
          <CardContent>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap", mb: 2 }}>
              <Typography variant="h1">
                {formatPeriod(batch.period_key)} batch {batch.batch_no}
              </Typography>
              <BatchStatusChip status={batch.status} />
              <Chip
                size="small"
                data-testid="balance-chip"
                color={data.balanced ? "success" : "error"}
                label={data.balanced ? "Balanced" : "Not balanced"}
              />
            </Box>
            <Box sx={{ display: "flex", gap: 4, flexWrap: "wrap", mb: 2 }}>
              <Fact label="Entries" value={String(batch.entry_count)} />
              <Fact label="Debit" value={formatMoney(batch.total_debit)} />
              <Fact label="Credit" value={formatMoney(batch.total_credit)} />
              <Fact label="Generated by" value={batch.generated_by_name} />
              {batch.approved_by_name && (
                <Fact label="Approved by" value={batch.approved_by_name} />
              )}
              {batch.posted_by_name && <Fact label="Posted by" value={batch.posted_by_name} />}
            </Box>
            {canApprove && (
              <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", alignItems: "center" }}>
                {batch.status === "DRAFT" && (
                  <Button
                    variant="contained"
                    disabled={generatedByMe}
                    onClick={() => setPending("approve")}
                  >
                    Approve
                  </Button>
                )}
                {batch.status === "APPROVED" && (
                  <>
                    <Button variant="contained" onClick={() => setPending("post")}>
                      Post
                    </Button>
                    <Button variant="outlined" onClick={() => setPending("send-back")}>
                      Send back
                    </Button>
                  </>
                )}
                {batch.status === "DRAFT" && generatedByMe && (
                  <Typography color="text.secondary" variant="body2">
                    You generated this batch, so someone else must approve it.
                  </Typography>
                )}
              </Box>
            )}
            {lifecycle.isError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {lifecycle.error.message}
              </Alert>
            )}
          </CardContent>
        </Card>
      )}
      {batch && (
        <ServerDataGrid<Line>
          path={path}
          columns={columns}
          label="Journal lines"
          emptyText="This batch has no lines."
          renderSummary={() => (
            <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
              <Button variant="outlined" size="small" href={`/api/v1${path}?format=csv`}>
                Export CSV
              </Button>
            </Box>
          )}
        />
      )}

      <Dialog open={pending !== null} onClose={() => setPending(null)} fullWidth maxWidth="sm">
        {pending && (
          <>
            <DialogTitle>{CONFIRM[pending].title}</DialogTitle>
            <DialogContent>
              <DialogContentText>{CONFIRM[pending].text}</DialogContentText>
              {pending === "send-back" && (
                <TextField
                  label="Reason (optional)"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  fullWidth
                  margin="normal"
                  slotProps={{ htmlInput: { maxLength: 1000 } }}
                />
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setPending(null)}>Cancel</Button>
              <Button
                variant="contained"
                disabled={lifecycle.isPending}
                onClick={() => lifecycle.mutate(pending)}
              >
                {CONFIRM[pending].button}
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      <Dialog open={reversing !== null} onClose={() => setReversing(null)} fullWidth maxWidth="sm">
        {reversing && (
          <>
            <DialogTitle>Reverse entry {reversing.entry_id}?</DialogTitle>
            <DialogContent>
              <DialogContentText>
                This books a mirror entry in a new draft batch of the current period, which still
                needs approval and posting. The original entry stays as it is. The contract&apos;s
                schedule does not change, so reversed revenue is not booked again automatically.
              </DialogContentText>
              <TextField
                label="Reason"
                required
                value={reversalReason}
                onChange={(event) => setReversalReason(event.target.value)}
                fullWidth
                margin="normal"
                slotProps={{ htmlInput: { maxLength: 1000 } }}
              />
              {reverse.isError && <Alert severity="error">{reverse.error.message}</Alert>}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setReversing(null)}>Cancel</Button>
              <Button
                variant="contained"
                disabled={reverse.isPending || reversalReason.trim().length < 3}
                onClick={() =>
                  reverse.mutate({ entryId: reversing.entry_id, text: reversalReason.trim() })
                }
              >
                Book reversal
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Stack>
  );
}
