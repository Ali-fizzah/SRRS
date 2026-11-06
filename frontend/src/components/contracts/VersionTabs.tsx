"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import SimpleTable from "@/components/contracts/SimpleTable";
import { apiGet, type Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type Contract = Schemas["ContractDetailOut"];
type Line = Schemas["ContractLineOut"];
type Obligation = Schemas["ObligationOut"];
type Delivery = Schemas["DeliveryOut"];
type Version = Schemas["VersionSummaryOut"];

const money = (value: string) => formatMoney(value);

function LinesTable({ lines }: { lines: Line[] }) {
  return (
    <SimpleTable<Line>
      label="Contract lines"
      rows={lines}
      rowKey={(line) => line.id}
      emptyText="This version has no lines."
      columns={[
        { header: "Line", cell: (l) => l.line_no },
        { header: "Product", cell: (l) => l.product_code },
        { header: "Separate?", cell: (l) => (l.is_separate_obligation ? "Yes" : "No") },
        { header: "Quantity", cell: (l) => l.quantity, align: "right" },
        { header: "Unit price", cell: (l) => money(l.unit_price), align: "right" },
        { header: "Discount", cell: (l) => money(l.discount), align: "right" },
        { header: "Net price", cell: (l) => money(l.net_price), align: "right" },
        { header: "Service", cell: (l) => `${l.service_start} to ${l.service_end}` },
        { header: "Completion", cell: (l) => l.completion_date ?? "" },
      ]}
    />
  );
}

function ObligationsTables({
  obligations,
  deliveries,
}: {
  obligations: Obligation[];
  deliveries: Delivery[];
}) {
  return (
    <Stack spacing={2}>
      <SimpleTable<Obligation>
        label="Performance obligations"
        rows={obligations}
        rowKey={(po) => po.id}
        emptyText="No obligations yet. Use Run recognition on the Contracts page."
        columns={[
          { header: "Line", cell: (po) => po.line_no },
          { header: "Product", cell: (po) => po.product_code },
          { header: "Method", cell: (po) => po.method },
          { header: "SSP", cell: (po) => money(po.ssp_amount), align: "right" },
          { header: "Allocated", cell: (po) => money(po.allocated_amount), align: "right" },
          { header: "Service", cell: (po) => `${po.service_start} to ${po.service_end}` },
          { header: "Status", cell: (po) => po.status },
        ]}
      />
      {deliveries.length > 0 && (
        <Box>
          <Typography variant="h2" sx={{ mb: 1 }}>
            Deliveries
          </Typography>
          <SimpleTable<Delivery>
            label="Deliveries"
            rows={deliveries}
            rowKey={(d) => d.delivery_code}
            emptyText=""
            columns={[
              { header: "Delivery", cell: (d) => d.delivery_code },
              { header: "Line", cell: (d) => d.line_no },
              { header: "Date", cell: (d) => d.delivery_date },
              { header: "Share delivered", cell: (d) => d.units_fraction, align: "right" },
            ]}
          />
        </Box>
      )}
    </Stack>
  );
}

function VersionsTable({ versions }: { versions: Version[] }) {
  return (
    <SimpleTable<Version>
      label="Contract versions"
      rows={versions}
      rowKey={(v) => v.version_no}
      emptyText="No versions."
      columns={[
        { header: "Version", cell: (v) => v.version_no },
        { header: "Event", cell: (v) => v.event_type },
        { header: "Effective", cell: (v) => v.effective_date },
        { header: "Term", cell: (v) => `${v.start_date} to ${v.end_date}` },
        { header: "Transaction price", cell: (v) => money(v.transaction_price), align: "right" },
        { header: "Booked in", cell: (v) => formatPeriod(v.booked_period) },
      ]}
    />
  );
}

/** Lines, obligations + allocation (for a chosen version), and the version list (plan §9). */
export default function VersionTabs({
  contract,
  id,
  tab,
}: {
  contract: Contract;
  id: string;
  tab: "lines" | "obligations" | "versions";
}) {
  const [versionNo, setVersionNo] = useState(contract.current_version_no);
  const version = useQuery({
    queryKey: ["/contracts", id, "versions", versionNo],
    queryFn: () => apiGet<Schemas["VersionDetailOut"]>(`/contracts/${id}/versions/${versionNo}`),
    enabled: tab !== "versions",
  });

  if (tab === "versions") return <VersionsTable versions={contract.versions} />;
  return (
    <Stack spacing={2}>
      {contract.versions.length > 1 && (
        <TextField
          id="version-select"
          select
          size="small"
          label="Version"
          value={versionNo}
          onChange={(event) => setVersionNo(Number(event.target.value))}
          sx={{ width: 260, bgcolor: "background.paper" }}
        >
          {contract.versions.map((v) => (
            <MenuItem key={v.version_no} value={v.version_no}>
              {v.version_no}: {v.event_type}
            </MenuItem>
          ))}
        </TextField>
      )}
      {version.isError && <Alert severity="error">{version.error.message}</Alert>}
      {version.isPending && <Skeleton variant="rounded" height={120} />}
      {version.data && tab === "lines" && <LinesTable lines={version.data.lines} />}
      {version.data && tab === "obligations" && (
        <ObligationsTables
          obligations={version.data.obligations}
          deliveries={version.data.deliveries}
        />
      )}
    </Stack>
  );
}
