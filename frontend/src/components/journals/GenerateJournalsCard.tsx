"use client";

import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import NextLink from "next/link";
import { useEffect } from "react";

import { apiGet, apiPost, type Schemas } from "@/lib/api/client";
import { isJobFinished, useJob } from "@/lib/api/useJob";
import { formatMoney, formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

type JournalResult = {
  batch_id: number | null;
  batch_no: number | null;
  entries: number;
  total_debit: string;
  drafts_replaced: number;
  skipped: { contract_code: string; reason: string; message: string }[];
};

const MAY_GENERATE = new Set(["ACCOUNTANT", "APPROVER", "ADMIN"]); // plan §8 Engine: ACCOUNTANT

/** Build the current period's journal batch and show what it did (plan §5.7, §10). */
export default function GenerateJournalsCard() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const period = useQuery({
    queryKey: ["/periods", "OPEN"],
    queryFn: () =>
      apiGet<{ items: Schemas["PeriodOut"][] }>("/periods", { status: "OPEN", page_size: 1 }),
  });
  const current = period.data?.items[0]?.period_key;

  const run = useMutation({
    mutationFn: (key: string) =>
      apiPost<Schemas["JobAccepted"]>(`/periods/${key}/journals/generate`),
  });
  const job = useJob(run.data?.job_id);
  const finished = isJobFinished(job.data);
  const running = run.isPending || (run.data !== undefined && !finished);

  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ queryKey: ["/journal-batches"] });
  }, [finished, queryClient]);

  if (!me.data?.roles.some((role) => MAY_GENERATE.has(role))) return null;

  const result = job.data?.status === "DONE" ? (job.data.result as JournalResult) : undefined;

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
          <Box sx={{ flexGrow: 1, minWidth: 240 }}>
            <Typography variant="h2" gutterBottom>
              Generate journals
            </Typography>
            <Typography color="text.secondary">
              {current
                ? `Books invoices, credit notes and revenue for ${formatPeriod(current)}. Run recognition first. A draft batch is rebuilt.`
                : "No period is open, so journals cannot be generated from here."}
            </Typography>
          </Box>
          <Button
            variant="contained"
            startIcon={<PlayArrowIcon />}
            disabled={!current || running}
            onClick={() => current && run.mutate(current)}
          >
            {running ? "Generating…" : "Generate journals"}
          </Button>
        </Box>

        {running && run.data && (
          <Box sx={{ mt: 2 }} role="status">
            <LinearProgress
              variant="determinate"
              value={job.data?.progress ?? 0}
              aria-label="Journal generation progress"
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
            Generation failed and saved nothing: {job.data.error}
          </Alert>
        )}
        {result && (
          <Alert
            severity={result.batch_id === null ? "info" : "success"}
            sx={{ mt: 2 }}
            data-testid="journal-result"
          >
            {result.batch_id === null ? (
              "Nothing new to book."
            ) : (
              <>
                <Link component={NextLink} href={`/journals/${result.batch_id}`}>
                  Batch {result.batch_no}
                </Link>
                {`: ${result.entries} entries, ${formatMoney(result.total_debit)} debits and credits.`}
                {result.drafts_replaced > 0 && " It replaces the previous draft."}
              </>
            )}
          </Alert>
        )}
        {result && result.skipped.length > 0 && (
          <Alert severity="warning" sx={{ mt: 1 }} data-testid="journal-skipped">
            {result.skipped.length} contract{result.skipped.length === 1 ? "" : "s"} not booked:
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
