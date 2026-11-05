"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useQuery } from "@tanstack/react-query";

import SimpleTable from "@/components/contracts/SimpleTable";
import { apiGet, type Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type Balance = Schemas["PeriodBalanceOut"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box>
      <Typography variant="h2" sx={{ mb: 1 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

/** Invoices, credit notes and the deferred / unbilled rollforward (plan §5.6). */
export default function BillingTab({ id }: { id: string }) {
  const billing = useQuery({
    queryKey: ["/contracts", id, "billing"],
    queryFn: () => apiGet<Schemas["ContractBillingOut"]>(`/contracts/${id}/billing`),
  });
  if (billing.isError) return <Alert severity="error">{billing.error.message}</Alert>;
  if (billing.isPending) return <Skeleton variant="rounded" height={160} />;
  const data = billing.data;

  return (
    <Stack spacing={3}>
      <Card data-testid="balance-summary">
        <CardContent sx={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Box>
            <Typography variant="caption" color="text.secondary" component="div">
              Deferred revenue
            </Typography>
            <Typography variant="h2" component="div">
              {formatMoney(data.deferred)}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" component="div">
              Unbilled receivable
            </Typography>
            <Typography variant="h2" component="div">
              {formatMoney(data.unbilled)}
            </Typography>
          </Box>
        </CardContent>
      </Card>

      <Section title="Rollforward">
        <SimpleTable<Balance>
          label="Deferred revenue rollforward"
          rows={data.balances}
          rowKey={(row) => row.period}
          emptyText="Nothing billed or recognised yet."
          columns={[
            { header: "Period", cell: (r) => formatPeriod(r.period) },
            {
              header: "Opening deferred",
              cell: (r) => formatMoney(r.opening_deferred),
              align: "right",
            },
            { header: "Billings", cell: (r) => formatMoney(r.billings), align: "right" },
            { header: "Credit notes", cell: (r) => formatMoney(r.credit_notes), align: "right" },
            { header: "Recognised", cell: (r) => formatMoney(r.recognised), align: "right" },
            {
              header: "Closing deferred",
              cell: (r) => formatMoney(r.closing_deferred),
              align: "right",
            },
            {
              header: "Closing unbilled",
              cell: (r) => formatMoney(r.closing_unbilled),
              align: "right",
            },
          ]}
        />
      </Section>

      <Section title="Invoices">
        <SimpleTable
          label="Invoices"
          rows={data.invoices}
          rowKey={(row) => row.invoice_number}
          emptyText="No invoices."
          columns={[
            { header: "Invoice", cell: (r) => r.invoice_number },
            { header: "Date", cell: (r) => r.invoice_date },
            { header: "Amount", cell: (r) => formatMoney(r.total_amount), align: "right" },
          ]}
        />
      </Section>

      <Section title="Credit notes">
        <SimpleTable
          label="Credit notes"
          rows={data.credit_notes}
          rowKey={(row) => row.credit_note_number}
          emptyText="No credit notes."
          columns={[
            { header: "Credit note", cell: (r) => r.credit_note_number },
            { header: "Invoice", cell: (r) => r.invoice_number },
            { header: "Date", cell: (r) => r.credit_date },
            { header: "Amount", cell: (r) => formatMoney(r.amount), align: "right" },
            { header: "Reason", cell: (r) => r.reason },
          ]}
        />
      </Section>
    </Stack>
  );
}
