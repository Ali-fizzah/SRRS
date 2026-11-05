"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";
import { BarChart } from "@mui/x-charts/BarChart";
import { LineChart } from "@mui/x-charts/LineChart";
import type { GridColDef } from "@mui/x-data-grid";
import { useQuery } from "@tanstack/react-query";
import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import Checklist from "@/components/periods/Checklist";
import ReportFrame, { type ReportFilters } from "@/components/reports/ReportFrame";
import ServerDataGrid from "@/components/ServerDataGrid";
import { apiGet, type Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type Revenue = Schemas["RevenueScheduleRow"];
type Rollforward = Schemas["RollforwardRow"];
type Trend = Schemas["RecognizedVsDeferredRow"];
type Register = Schemas["JournalRegisterRow"];
type GlSummary = Schemas["GlSummaryRow"];
type Mrr = Schemas["MrrArrRow"];
type CloseRow = Schemas["CloseStatusRow"];
type ValidationRow = Schemas["ValidationLogRow"];

const period = (value: string) => formatPeriod(value);
const money = (value: string) => formatMoney(value);
const moneyColumn = {
  width: 130,
  align: "right" as const,
  headerAlign: "right" as const,
  valueFormatter: money,
};

/** Charts plot positions, so a number is fine here; figures shown as text stay strings (D1). */
const plot = (value: string) => Number(value);

function ContractLink({ id, code }: { id: number; code: string }) {
  return (
    <Link component={NextLink} href={`/contracts/${id}`}>
      {code}
    </Link>
  );
}

/** Every row of a report for its chart: the 100-row page limit is 8 years of months. */
function useChartRows<T>(path: string, filters: ReportFilters) {
  return useQuery({
    queryKey: [path, "chart", JSON.stringify(filters)],
    queryFn: () => apiGet<{ items: T[] }>(path, { ...filters, page_size: 100 }),
  });
}

function ChartCard({
  title,
  error,
  children,
}: {
  title: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent>
        <Typography variant="h2" gutterBottom>
          {title}
        </Typography>
        {error ? <Alert severity="error">{error}</Alert> : children}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- revenue schedule

const REVENUE_COLUMNS: GridColDef<Revenue>[] = [
  {
    field: "contract_code",
    headerName: "Contract",
    width: 190,
    renderCell: ({ row }) => <ContractLink id={row.contract_id} code={row.contract_code} />,
  },
  { field: "customer_name", headerName: "Customer", flex: 1, minWidth: 150 },
  { field: "line_no", headerName: "Line", type: "number", width: 70 },
  { field: "product_code", headerName: "Product", flex: 1, minWidth: 150 },
  { field: "service_period", headerName: "Earned", width: 100, valueFormatter: period },
  {
    field: "posting_period",
    headerName: "Booked in",
    width: 170,
    valueFormatter: (value: string | null) => (value ? formatPeriod(value) : "Not yet"),
    renderCell: ({ row, formattedValue }) => (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, height: "100%" }}>
        {formattedValue}
        {row.is_catch_up && <Chip size="small" label="Catch-up" variant="outlined" />}
      </Box>
    ),
  },
  { field: "amount", headerName: "Amount", ...moneyColumn },
  { field: "status", headerName: "Status", width: 110 },
];

export function RevenueScheduleReport() {
  return (
    <ReportFrame
      title="Revenue schedule"
      subtitle="Revenue per contract line per month, by the month it is earned."
      path="/reports/revenue-schedule"
      filters={["period", "customer", "contract", "product"]}
    >
      {(filters) => (
        <ServerDataGrid<Revenue>
          path="/reports/revenue-schedule"
          columns={REVENUE_COLUMNS}
          label="Revenue schedule"
          emptyText="No schedule lines match these filters."
          filters={filters}
          renderSummary={(page) => (
            <Typography data-testid="report-total">
              {page.total} lines, total <strong>{money(page.total_amount as string)}</strong>
            </Typography>
          )}
        />
      )}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- rollforward

const ROLLFORWARD_FIGURES: GridColDef<Rollforward>[] = [
  { field: "opening_deferred", headerName: "Opening", sortable: false, ...moneyColumn },
  { field: "billings", headerName: "Billings", ...moneyColumn },
  { field: "billed_to_unbilled", headerName: "To unbilled", sortable: false, ...moneyColumn },
  { field: "credit_notes", headerName: "Credit notes", sortable: false, ...moneyColumn },
  { field: "adjustments", headerName: "Reversals", sortable: false, ...moneyColumn },
  {
    field: "recognised_from_deferred",
    headerName: "Recognised",
    sortable: false,
    ...moneyColumn,
  },
  { field: "closing_deferred", headerName: "Closing", ...moneyColumn },
  { field: "closing_unbilled", headerName: "Unbilled", sortable: false, ...moneyColumn },
];

const BY_PERIOD: GridColDef<Rollforward>[] = [
  {
    field: "period",
    headerName: "Period",
    width: 110,
    renderCell: ({ row }) => (
      <Link
        component={NextLink}
        href={`/reports/deferred-rollforward?group_by=contract&period_from=${row.period}&period_to=${row.period}`}
      >
        {formatPeriod(row.period)}
      </Link>
    ),
  },
  ...ROLLFORWARD_FIGURES,
];

const BY_CONTRACT: GridColDef<Rollforward>[] = [
  { field: "period", headerName: "Period", width: 100, valueFormatter: period },
  {
    field: "contract_code",
    headerName: "Contract",
    width: 190,
    renderCell: ({ row }) =>
      row.contract_id !== null && row.contract_id !== undefined ? (
        <ContractLink id={row.contract_id} code={row.contract_code ?? ""} />
      ) : null,
  },
  ...ROLLFORWARD_FIGURES,
];

function RollforwardChart({ filters }: { filters: ReportFilters }) {
  const rows = useChartRows<Rollforward>("/reports/deferred-rollforward", filters);
  const items = rows.data?.items ?? [];
  return (
    <ChartCard title="Deferred revenue at month end" error={rows.error?.message}>
      {items.length > 0 && (
        <BarChart
          height={260}
          xAxis={[{ scaleType: "band", data: items.map((row) => formatPeriod(row.period)) }]}
          series={[
            { label: "Closing deferred", data: items.map((row) => plot(row.closing_deferred)) },
          ]}
        />
      )}
    </ChartCard>
  );
}

function RollforwardBody({ filters }: { filters: ReportFilters }) {
  const byContract = useSearchParams().get("group_by") === "contract";
  return (
    <>
      {!byContract && <RollforwardChart filters={filters} />}
      {byContract && (
        <Alert severity="info" className="no-print">
          Showing each contract behind this month.{" "}
          <Link component={NextLink} href="/reports/deferred-rollforward">
            Back to all months
          </Link>
        </Alert>
      )}
      <ServerDataGrid<Rollforward>
        path="/reports/deferred-rollforward"
        columns={byContract ? BY_CONTRACT : BY_PERIOD}
        label="Deferred revenue rollforward"
        emptyText="No activity matches these filters."
        filters={filters}
      />
    </>
  );
}

export function DeferredRollforwardReport() {
  return (
    <Suspense>
      <RollforwardKeyed />
    </Suspense>
  );
}

function RollforwardKeyed() {
  // A link from a month changes the URL on the same page, so the filter bar starts again from it.
  const key = useSearchParams().toString();
  return (
    <ReportFrame
      key={key}
      title="Deferred revenue rollforward"
      subtitle="Opening, billings, credit notes, recognised, closing. Click a month to see its contracts."
      path="/reports/deferred-rollforward"
      filters={["period", "customer", "contract", "product"]}
    >
      {(filters) => <RollforwardBody filters={filters} />}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- trend

const TREND_COLUMNS: GridColDef<Trend>[] = [
  { field: "period", headerName: "Period", width: 110, valueFormatter: period },
  { field: "recognised", headerName: "Recognised", ...moneyColumn },
  { field: "deferred", headerName: "Deferred", ...moneyColumn },
  { field: "unbilled", headerName: "Unbilled", ...moneyColumn },
];

function TrendChart({ filters }: { filters: ReportFilters }) {
  const rows = useChartRows<Trend>("/reports/recognized-vs-deferred", filters);
  const items = rows.data?.items ?? [];
  return (
    <ChartCard title="Recognised revenue and deferred balance" error={rows.error?.message}>
      {items.length > 0 && <TrendLines items={items} />}
    </ChartCard>
  );
}

export function TrendLines({ items, height = 280 }: { items: Trend[]; height?: number }) {
  return (
    <LineChart
      height={height}
      xAxis={[{ scaleType: "point", data: items.map((row) => formatPeriod(row.period)) }]}
      series={[
        { label: "Recognised", curve: "linear", data: items.map((row) => plot(row.recognised)) },
        { label: "Deferred", curve: "linear", data: items.map((row) => plot(row.deferred)) },
      ]}
    />
  );
}

export function TrendReport() {
  return (
    <ReportFrame
      title="Trend"
      subtitle="Monthly recognised revenue and the deferred balance at each month end."
      path="/reports/recognized-vs-deferred"
      filters={["period", "customer", "contract", "product"]}
    >
      {(filters) => (
        <>
          <TrendChart filters={filters} />
          <ServerDataGrid<Trend>
            path="/reports/recognized-vs-deferred"
            columns={TREND_COLUMNS}
            label="Recognised and deferred by month"
            emptyText="No activity matches these filters."
            filters={filters}
          />
        </>
      )}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- journal register

const blankIfZero = (value: string) => (Number(value) === 0 ? "" : formatMoney(value));

const REGISTER_COLUMNS: GridColDef<Register>[] = [
  { field: "period_key", headerName: "Period", width: 100, valueFormatter: period },
  {
    field: "batch_no",
    headerName: "Batch",
    width: 90,
    renderCell: ({ row }) => (
      <Link component={NextLink} href={`/journals/${row.batch_id}`}>
        Batch {row.batch_no}
      </Link>
    ),
  },
  { field: "batch_status", headerName: "Status", width: 110, sortable: false },
  { field: "entry_type", headerName: "Type", width: 170 },
  {
    field: "contract_code",
    headerName: "Contract",
    width: 190,
    renderCell: ({ row }) => <ContractLink id={row.contract_id} code={row.contract_code} />,
  },
  {
    field: "account_code",
    headerName: "Account",
    flex: 1,
    minWidth: 200,
    valueGetter: (_value, row) => `${row.account_code} ${row.account_name}`,
  },
  { field: "debit", headerName: "Debit", ...moneyColumn, valueFormatter: blankIfZero },
  { field: "credit", headerName: "Credit", ...moneyColumn, valueFormatter: blankIfZero },
];

export function JournalRegisterReport() {
  return (
    <ReportFrame
      title="Journal register"
      subtitle="Every journal line by period, status and account."
      path="/reports/journal-register"
      filters={["period", "customer", "contract", "product", "account"]}
    >
      {(filters) => (
        <ServerDataGrid<Register>
          path="/reports/journal-register"
          columns={REGISTER_COLUMNS}
          label="Journal register"
          emptyText="No journal lines match these filters."
          filters={filters}
        />
      )}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- GL summary

const GL_COLUMNS: GridColDef<GlSummary>[] = [
  {
    field: "period_key",
    headerName: "Period",
    width: 110,
    renderCell: ({ row }) => (
      <Link
        component={NextLink}
        href={`/reports/journal-register?period_from=${row.period_key}&period_to=${row.period_key}&account=${row.account_code}`}
      >
        {formatPeriod(row.period_key)}
      </Link>
    ),
  },
  { field: "account_code", headerName: "Account", width: 100 },
  { field: "account_name", headerName: "Name", flex: 1, minWidth: 200, sortable: false },
  { field: "debit", headerName: "Debit", ...moneyColumn },
  { field: "credit", headerName: "Credit", ...moneyColumn },
  { field: "net", headerName: "Net (debit - credit)", ...moneyColumn, width: 160 },
];

export function GlSummaryReport() {
  return (
    <ReportFrame
      title="GL summary"
      subtitle="Debit, credit and net per account per period, from posted batches. Click a period to see its lines."
      path="/reports/gl-summary"
      filters={["period", "customer", "contract", "product"]}
    >
      {(filters) => (
        <ServerDataGrid<GlSummary>
          path="/reports/gl-summary"
          columns={GL_COLUMNS}
          label="GL summary"
          emptyText="No posted journal lines match these filters."
          filters={filters}
        />
      )}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- MRR / ARR

const MRR_COLUMNS: GridColDef<Mrr>[] = [
  { field: "period", headerName: "Period", width: 110, valueFormatter: period },
  { field: "mrr", headerName: "MRR", ...moneyColumn },
  { field: "arr", headerName: "ARR", ...moneyColumn, width: 150 },
];

function MrrChart({ filters }: { filters: ReportFilters }) {
  const rows = useChartRows<Mrr>("/reports/mrr-arr", filters);
  const items = rows.data?.items ?? [];
  return (
    <ChartCard title="MRR by month (non-GAAP)" error={rows.error?.message}>
      {items.length > 0 && (
        <LineChart
          height={260}
          xAxis={[{ scaleType: "point", data: items.map((row) => formatPeriod(row.period)) }]}
          series={[{ label: "MRR", curve: "linear", data: items.map((row) => plot(row.mrr)) }]}
        />
      )}
    </ChartCard>
  );
}

export function MrrArrReport() {
  return (
    <ReportFrame
      title="MRR / ARR"
      subtitle="Non-GAAP: monthly and annual recurring revenue. This is not recognised revenue."
      path="/reports/mrr-arr"
      filters={["period", "customer", "contract", "product"]}
    >
      {(filters) => (
        <>
          <Alert severity="info" data-testid="non-gaap">
            Non-GAAP measure, shown apart from recognised revenue (plan §5.9).
          </Alert>
          <MrrChart filters={filters} />
          <ServerDataGrid<Mrr>
            path="/reports/mrr-arr"
            columns={MRR_COLUMNS}
            label="MRR and ARR by month"
            emptyText="No ratable contract lines match these filters."
            filters={filters}
          />
        </>
      )}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- close status

const CLOSE_COLUMNS: GridColDef<CloseRow>[] = [
  { field: "period_key", headerName: "Period", width: 110, valueFormatter: period },
  { field: "status", headerName: "Status", width: 120 },
  { field: "batches", headerName: "Batches", type: "number", width: 100, sortable: false },
  { field: "posted_batches", headerName: "Posted", type: "number", width: 100, sortable: false },
  { field: "closed_by_name", headerName: "Closed by", flex: 1, minWidth: 160, sortable: false },
  {
    field: "closed_at",
    headerName: "Closed at",
    width: 190,
    sortable: false,
    valueFormatter: (value: string | null) => (value ? new Date(value).toLocaleString() : ""),
  },
];

export function CloseStatusReport() {
  return (
    <ReportFrame
      title="Close status"
      subtitle="The state of each period, and the checklist of the current one."
      path="/reports/close-status"
      filters={["period"]}
    >
      {(filters) => (
        <ServerDataGrid<CloseRow>
          path="/reports/close-status"
          columns={CLOSE_COLUMNS}
          label="Close status"
          emptyText="No periods match these filters."
          filters={filters}
          renderSummary={(page) => {
            const current = page.current as Schemas["ChecklistOut"] | null;
            return current ? (
              <Card sx={{ mb: 1 }}>
                <CardContent>
                  <Typography variant="h2" gutterBottom>
                    {formatPeriod(current.period_key)} checklist ({current.status})
                  </Typography>
                  <Checklist items={current.items} />
                </CardContent>
              </Card>
            ) : null;
          }}
        />
      )}
    </ReportFrame>
  );
}

// --------------------------------------------------------------------------- validation log

const VALIDATION_COLUMNS: GridColDef<ValidationRow>[] = [
  {
    field: "filename",
    headerName: "File",
    width: 200,
    renderCell: ({ row }) => (
      <Link component={NextLink} href={`/uploads/${row.upload_id}`}>
        {row.filename}
      </Link>
    ),
  },
  { field: "period_key", headerName: "Period", width: 100, valueFormatter: period },
  { field: "row_number", headerName: "Row", type: "number", width: 80 },
  { field: "column_name", headerName: "Column", width: 150, sortable: false },
  { field: "error_code", headerName: "Code", width: 90 },
  { field: "message", headerName: "Message", flex: 1, minWidth: 260, sortable: false },
  { field: "raw_value", headerName: "Value", width: 150, sortable: false },
];

export function ValidationLogReport() {
  return (
    <ReportFrame
      title="Validation log"
      subtitle="Every error found in every upload (E001 to E014)."
      path="/reports/validation-log"
      filters={["period"]}
    >
      {(filters) => (
        <ServerDataGrid<ValidationRow>
          path="/reports/validation-log"
          columns={VALIDATION_COLUMNS}
          label="Validation log"
          emptyText="No validation errors match these filters."
          filters={filters}
          wrapText
        />
      )}
    </ReportFrame>
  );
}
