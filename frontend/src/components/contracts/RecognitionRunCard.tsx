"use client";

import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import LinearProgress from "@mui/material/LinearProgress";
import Typography from "@mui/material/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiGet, postRecognitionRun, type Schemas } from "@/lib/api/client";
import { isJobFinished, useJob } from "@/lib/api/useJob";
import { formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

type RunResult = {
  contracts_generated: number;
  schedule_lines_created: number;
  skipped: { contract_code: string; reason: string; message: string }[];
};

const MAY_RUN = new Set(["ACCOUNTANT", "APPROVER", "ADMIN"]); // plan §8 Engine: ACCOUNTANT

/** Start a recognition run for the current period and show what it did (plan §5.4, §10). */
export default function RecognitionRunCard() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const period = useQuery({
    queryKey: ["/periods", "OPEN"],
    queryFn: () =>
      apiGet<{ items: Schemas["PeriodOut"][] }>("/periods", { status: "OPEN", page_size: 1 }),
  });
  const current = period.data?.items[0]?.period_key;

  const run = useMutation({ mutationFn: postRecognitionRun });
  const job = useJob(run.data?.job_id);
  const finished = isJobFinished(job.data);
  const running = run.isPending || (run.data !== undefined && !finished);

  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ queryKey: ["/contracts"] });
  }, [finished, queryClient]);

  if (!me.data?.roles.some((role) => MAY_RUN.has(role))) return null;

  const result = job.data?.status === "DONE" ? (job.data.result as RunResult) : undefined;

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
          <Box sx={{ flexGrow: 1, minWidth: 240 }}>
            <Typography variant="h2" gutterBottom>
              Recognition run
            </Typography>
            <Typography color="text.secondary">
              {current
                ? `Builds revenue schedules for new contracts. Current period: ${formatPeriod(current)}.`
                : "No period is open, so a run cannot start from here."}
            </Typography>
          </Box>
          <Button
            variant="contained"
            startIcon={<PlayArrowIcon />}
            disabled={!current || running}
            onClick={() => current && run.mutate(current)}
          >
            {running ? "Running…" : "Run recognition"}
          </Button>
        </Box>

        {running && run.data && (
          <Box sx={{ mt: 2 }} role="status">
            <LinearProgress
              variant="determinate"
              value={job.data?.progress ?? 0}
              aria-label="Recognition run progress"
            />
          </Box>
        )}
        {run.isError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {run.error.message}
          </Alert>
        )}
        {job.data?.status === "FAILED" && (
          <Alert severity="error" sx={{ mt: 2 }}>
            The run failed and saved nothing: {job.data.error}
          </Alert>
        )}
        {result && (
          <Alert severity="success" sx={{ mt: 2 }} data-testid="run-result">
            {result.contracts_generated === 0
              ? "Nothing new to schedule."
              : `${result.contracts_generated} contract${result.contracts_generated === 1 ? "" : "s"} scheduled, ${result.schedule_lines_created} schedule lines created.`}
          </Alert>
        )}
        {result && result.skipped.length > 0 && (
          <Alert severity="warning" sx={{ mt: 1 }} data-testid="run-skipped">
            {result.skipped.length} contract{result.skipped.length === 1 ? "" : "s"} not scheduled:
            <Box component="ul" sx={{ m: 0, pl: 2 }}>
              {result.skipped.slice(0, 20).map((skip) => (
                <li key={skip.contract_code}>
                  {skip.contract_code}: {skip.message}
                </li>
              ))}
            </Box>
            {result.skipped.length > 20 && `…and ${result.skipped.length - 20} more.`}
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
