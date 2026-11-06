"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import Typography from "@mui/material/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import NextLink from "next/link";
import { useState } from "react";

import Checklist from "@/components/periods/Checklist";
import { apiGet, apiPost, type Schemas } from "@/lib/api/client";
import { useCurrentPeriod } from "@/lib/api/useCurrentPeriod";
import { formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

const MAY_START = new Set(["ACCOUNTANT", "APPROVER", "ADMIN"]); // plan §8: start-close ACCOUNTANT
const MAY_CLOSE = new Set(["APPROVER", "ADMIN"]); // plan §8: close APPROVER
const STEPS = ["Open", "Closing", "Closed"];

/** Close the current period with a live checklist (plan §5.8, §9). */
export default function CloseWorkflow() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const current = useCurrentPeriod();
  const period = current.data;
  const checklist = useQuery({
    queryKey: ["/periods", period?.period_key, "checklist"],
    queryFn: () => apiGet<Schemas["ChecklistOut"]>(`/periods/${period?.period_key}/checklist`),
    enabled: Boolean(period),
    refetchInterval: 15000, // live: journals and uploads change it from other pages
  });
  const [confirming, setConfirming] = useState(false);

  const action = useMutation({
    mutationFn: (name: "start-close" | "close") =>
      apiPost<Schemas["PeriodOut"]>(`/periods/${period?.period_key}/${name}`),
    onSuccess: async () => {
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ["/periods"] });
    },
    onError: () => setConfirming(false),
  });

  const roles = me.data?.roles ?? [];
  const canStart = roles.some((role) => MAY_START.has(role));
  const canClose = roles.some((role) => MAY_CLOSE.has(role));
  const items = checklist.data?.items ?? [];
  const passed = items.filter((item) => item.status !== "fail").length;

  if (current.isPending) return <Skeleton variant="rounded" height={320} />;
  if (current.isError) return <Alert severity="error">{current.error.message}</Alert>;
  if (!period) return <Alert severity="warning">No period is open.</Alert>;

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center", mb: 2 }}>
          <Typography variant="h2" sx={{ flexGrow: 1 }} data-testid="current-period">
            Current period: {formatPeriod(period.period_key)}
          </Typography>
          {period.status === "OPEN" && canStart && (
            <Button variant="contained" onClick={() => action.mutate("start-close")}>
              Start close
            </Button>
          )}
          {period.status === "CLOSING" && canClose && (
            <Button
              variant="contained"
              disabled={!checklist.data?.can_close}
              onClick={() => setConfirming(true)}
            >
              Close period
            </Button>
          )}
        </Box>
        <Stepper
          activeStep={period.status === "OPEN" ? 0 : 1}
          sx={{ mb: 3 }}
          aria-label="Period status"
        >
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
        {period.status === "CLOSING" && (
          <Alert severity="info" sx={{ mb: 2 }}>
            New uploads are blocked. You can still{" "}
            <NextLink href="/contracts">run recognition</NextLink> and{" "}
            <NextLink href="/journals">generate journals</NextLink>.
          </Alert>
        )}
        {action.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {action.error.message}
          </Alert>
        )}
        <Typography sx={{ mb: 1.5, fontWeight: 500 }} data-testid="checklist-progress">
          Checklist: {passed} of {items.length} ready
        </Typography>
        {checklist.isError && <Alert severity="error">{checklist.error.message}</Alert>}
        <Stack>
          <Checklist items={items} />
        </Stack>
      </CardContent>

      <Dialog open={confirming} onClose={() => setConfirming(false)} fullWidth maxWidth="sm">
        <DialogTitle>Close {formatPeriod(period.period_key)}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            The next period opens. Nothing can be booked in this one any more; later corrections go
            in the current period.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirming(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={action.isPending}
            onClick={() => action.mutate("close")}
          >
            Close period
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
