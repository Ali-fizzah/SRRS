"use client";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import type { GridColDef } from "@mui/x-data-grid";
import { useQuery } from "@tanstack/react-query";
import NextLink from "next/link";

import ServerDataGrid from "@/components/ServerDataGrid";
import { apiGet, type Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type ScheduleRow = Schemas["ScheduleLineOut"];

const COLUMNS: GridColDef<ScheduleRow>[] = [
  {
    field: "service_period",
    headerName: "Service period",
    width: 140,
    valueFormatter: (value: string) => formatPeriod(value),
  },
  {
    field: "amount",
    headerName: "Amount",
    width: 130,
    align: "right",
    headerAlign: "right",
    valueFormatter: (value: string) => formatMoney(value),
  },
  { field: "line_no", headerName: "Line", type: "number", width: 70 },
  { field: "product_code", headerName: "Product", flex: 1, minWidth: 180 },
  { field: "method", headerName: "Method", width: 170, sortable: false },
  { field: "status", headerName: "Status", width: 110 },
  {
    field: "posting_period",
    headerName: "Posting period",
    width: 140,
    valueFormatter: (value: string | null) => (value ? formatPeriod(value) : "Not yet"),
  },
];

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

/** Contract page (plan §9). Task P2-T5 builds the schedule tab; P3-T8 adds the other tabs. */
export default function ContractDetail({ id }: { id: string }) {
  const contract = useQuery({
    queryKey: ["/contracts", id],
    queryFn: () => apiGet<Schemas["ContractOut"]>(`/contracts/${id}`),
  });
  const data = contract.data;

  return (
    <Stack spacing={2}>
      <Box>
        <Button component={NextLink} href="/contracts" startIcon={<ArrowBackIcon />} size="small">
          All contracts
        </Button>
      </Box>
      {contract.isError && <Alert severity="error">{contract.error.message}</Alert>}
      {contract.isPending && <Skeleton variant="rounded" height={120} />}
      {data && (
        <Card>
          <CardContent>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap", mb: 2 }}>
              <Typography variant="h1" sx={{ overflowWrap: "anywhere" }}>
                {data.contract_code}
              </Typography>
              <Chip size="small" label={data.status} />
            </Box>
            <Box sx={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              <Fact label="Customer" value={data.customer_name} />
              <Fact label="Term" value={`${data.start_date} to ${data.end_date}`} />
              <Fact label="Transaction price" value={formatMoney(data.transaction_price)} />
              <Fact label="Booked in" value={formatPeriod(data.booked_period)} />
              <Fact label="Version" value={String(data.current_version_no)} />
            </Box>
          </CardContent>
        </Card>
      )}
      {data && (
        <Box>
          <Tabs value="schedule" aria-label="Contract details" sx={{ mb: 2 }}>
            <Tab value="schedule" label="Schedule" />
          </Tabs>
          <ServerDataGrid<ScheduleRow>
            path={`/contracts/${id}/schedule`}
            columns={COLUMNS}
            label="Revenue schedule"
            emptyText="No schedule yet. Use Run recognition on the Contracts page."
            renderSummary={(page) => (
              <Box
                data-testid="schedule-summary"
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 2,
                  flexWrap: "wrap",
                  mb: 1,
                }}
              >
                <Typography sx={{ flexGrow: 1 }}>
                  {page.total} schedule line{page.total === 1 ? "" : "s"}, total{" "}
                  <strong>{formatMoney(page.total_amount as string)}</strong>
                </Typography>
                <Button
                  variant="outlined"
                  size="small"
                  href={`/api/v1/contracts/${id}/schedule?format=csv`}
                >
                  Export CSV
                </Button>
              </Box>
            )}
          />
        </Box>
      )}
    </Stack>
  );
}
