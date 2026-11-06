"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useQuery } from "@tanstack/react-query";
import NextLink from "next/link";

import ApiHealth from "@/components/ApiHealth";
import { TrendLines } from "@/components/reports/ReportPages";
import StatusChip from "@/components/uploads/StatusChip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { useCurrentPeriod } from "@/lib/api/useCurrentPeriod";
import { formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

const MAY_SEE_REPORTS = new Set(["ACCOUNTANT", "APPROVER", "ADMIN"]); // plan §8 Reports

/** Current period, checklist progress, recognised vs deferred, recent uploads (plan §9). */
export default function Dashboard() {
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const seesReports = me.data?.roles.some((role) => MAY_SEE_REPORTS.has(role)) ?? false;
  const current = useCurrentPeriod();
  const key = current.data?.period_key;
  const checklist = useQuery({
    queryKey: ["/periods", key, "checklist"],
    queryFn: () => apiGet<Schemas["ChecklistOut"]>(`/periods/${key}/checklist`),
    enabled: Boolean(key),
  });
  const trend = useQuery({
    queryKey: ["/reports/recognized-vs-deferred", "dashboard"],
    queryFn: () =>
      apiGet<{ items: Schemas["RecognizedVsDeferredRow"][] }>("/reports/recognized-vs-deferred", {
        page_size: 100,
      }),
    enabled: seesReports,
  });
  const uploads = useQuery({
    queryKey: ["/uploads", "dashboard"],
    queryFn: () => apiGet<{ items: Schemas["UploadOut"][] }>("/uploads", { page_size: 5 }),
  });

  const items = checklist.data?.items ?? [];
  const ready = items.filter((item) => item.status !== "fail").length;

  return (
    <Stack spacing={2}>
      <Typography variant="h1">Dashboard</Typography>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
        <Card>
          <CardContent>
            <Typography variant="h2" gutterBottom>
              Current period
            </Typography>
            {current.isError && <Alert severity="error">{current.error.message}</Alert>}
            {current.data && (
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Typography sx={{ fontSize: 28, fontWeight: 600 }} data-testid="dashboard-period">
                  {formatPeriod(current.data.period_key)}
                </Typography>
                <Chip size="small" label={current.data.status} />
              </Box>
            )}
            <Button component={NextLink} href="/periods" size="small" sx={{ mt: 1, ml: -0.5 }}>
              Go to the close workflow
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <Typography variant="h2" gutterBottom>
              Close checklist
            </Typography>
            <Typography data-testid="dashboard-checklist" gutterBottom>
              {ready} of {items.length} ready
            </Typography>
            <LinearProgress
              variant="determinate"
              value={items.length ? (ready / items.length) * 100 : 0}
              aria-label="Close checklist progress"
            />
          </CardContent>
        </Card>
      </Box>
      {seesReports && (
        <Card>
          <CardContent>
            <Typography variant="h2" gutterBottom>
              Recognised vs deferred
            </Typography>
            {trend.isError && <Alert severity="error">{trend.error.message}</Alert>}
            {trend.data && trend.data.items.length === 0 && (
              <Typography color="text.secondary">No revenue has been booked yet.</Typography>
            )}
            {trend.data && trend.data.items.length > 0 && (
              <TrendLines items={trend.data.items} height={220} />
            )}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardContent>
          <Typography variant="h2" gutterBottom>
            Recent uploads
          </Typography>
          {uploads.isError && <Alert severity="error">{uploads.error.message}</Alert>}
          {uploads.data?.items.length === 0 && (
            <Typography color="text.secondary">No files have been uploaded yet.</Typography>
          )}
          <Stack spacing={1}>
            {uploads.data?.items.map((upload) => (
              <Box key={upload.id} sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                <StatusChip status={upload.status} />
                <Link
                  component={NextLink}
                  href={`/uploads/${upload.id}`}
                  sx={{ overflowWrap: "anywhere" }}
                >
                  {upload.original_filename}
                </Link>
              </Box>
            ))}
          </Stack>
        </CardContent>
      </Card>
      <ApiHealth />
    </Stack>
  );
}
