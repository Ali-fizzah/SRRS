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
import { useQuery } from "@tanstack/react-query";
import NextLink from "next/link";
import { useState } from "react";

import BillingTab from "@/components/contracts/BillingTab";
import ScheduleTab from "@/components/contracts/ScheduleTab";
import SourceRowsTab from "@/components/contracts/SourceRowsTab";
import VersionTabs from "@/components/contracts/VersionTabs";
import { apiGet, type Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type TabName = "schedule" | "lines" | "obligations" | "versions" | "billing" | "source";

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

/** Contract page (plan §9): summary, then tabs down to the uploaded source rows. */
export default function ContractDetail({ id }: { id: string }) {
  const [tab, setTab] = useState<TabName>("schedule");
  const contract = useQuery({
    queryKey: ["/contracts", id],
    queryFn: () => apiGet<Schemas["ContractDetailOut"]>(`/contracts/${id}`),
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
          <Tabs
            value={tab}
            onChange={(_event, value: TabName) => setTab(value)}
            aria-label="Contract details"
            variant="scrollable"
            scrollButtons="auto"
            sx={{ mb: 2 }}
          >
            <Tab value="schedule" label="Schedule" />
            <Tab value="lines" label="Lines" />
            <Tab value="obligations" label="Obligations" />
            <Tab value="versions" label="Versions" />
            <Tab value="billing" label="Billing" />
            <Tab value="source" label="Source rows" />
          </Tabs>
          {tab === "schedule" && <ScheduleTab id={id} />}
          {(tab === "lines" || tab === "obligations" || tab === "versions") && (
            <VersionTabs contract={data} id={id} tab={tab} />
          )}
          {tab === "billing" && <BillingTab id={id} />}
          {tab === "source" && <SourceRowsTab id={id} />}
        </Box>
      )}
    </Stack>
  );
}
