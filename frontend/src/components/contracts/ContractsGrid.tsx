"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Link from "@mui/material/Link";
import TextField from "@mui/material/TextField";
import type { GridColDef } from "@mui/x-data-grid";
import NextLink from "next/link";
import { useEffect, useState } from "react";

import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";

type Contract = Schemas["ContractOut"];

const COLUMNS: GridColDef<Contract>[] = [
  {
    field: "contract_code",
    headerName: "Contract",
    width: 180,
    renderCell: ({ row }) => (
      <Link component={NextLink} href={`/contracts/${row.id}`}>
        {row.contract_code}
      </Link>
    ),
  },
  { field: "customer_name", headerName: "Customer", flex: 1, minWidth: 180 },
  { field: "status", headerName: "Status", width: 110 },
  { field: "start_date", headerName: "Start", width: 115 },
  { field: "end_date", headerName: "End", width: 115 },
  {
    field: "transaction_price",
    headerName: "Transaction price",
    width: 150,
    align: "right",
    headerAlign: "right",
    valueFormatter: (value: string) => formatMoney(value),
  },
  {
    field: "booked_period",
    headerName: "Booked",
    width: 100,
    valueFormatter: (value: string) => formatPeriod(value),
  },
  {
    field: "has_schedule",
    headerName: "Schedule",
    width: 120,
    sortable: false,
    renderCell: ({ row }) => (
      <Chip
        size="small"
        label={row.has_schedule ? "Generated" : "Not yet"}
        color={row.has_schedule ? "success" : "default"}
      />
    ),
  },
];

type FilterName = "customer" | "contract" | "product";
const FILTERS: { name: FilterName; label: string }[] = [
  { name: "contract", label: "Contract" },
  { name: "customer", label: "Customer" },
  { name: "product", label: "Product" },
];

/** Contract list with filters (plan §9). The server filters, sorts and exports. */
export default function ContractsGrid() {
  const [typed, setTyped] = useState<Record<FilterName, string>>({
    contract: "",
    customer: "",
    product: "",
  });
  const [applied, setApplied] = useState(typed);

  // Ask the server once typing pauses, not on every key press.
  useEffect(() => {
    const timer = setTimeout(() => setApplied(typed), 300);
    return () => clearTimeout(timer);
  }, [typed]);

  const filters = Object.fromEntries(
    Object.entries(applied)
      .map(([name, value]) => [name, value.trim()] as const)
      .filter(([, value]) => value !== ""),
  );

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", alignItems: "center" }}>
        {FILTERS.map(({ name, label }) => (
          <TextField
            key={name}
            id={`filter-${name}`}
            label={label}
            size="small"
            value={typed[name]}
            onChange={(event) => setTyped({ ...typed, [name]: event.target.value })}
            sx={{ width: { xs: "100%", sm: 190 }, bgcolor: "background.paper" }}
          />
        ))}
        <Box sx={{ flexGrow: 1 }} />
        <Button
          variant="outlined"
          href={`/api/v1/contracts?${new URLSearchParams({ ...filters, format: "csv" })}`}
        >
          Export CSV
        </Button>
      </Box>
      <ServerDataGrid<Contract>
        path="/contracts"
        columns={COLUMNS}
        label="Contracts"
        emptyText={
          Object.keys(filters).length
            ? "No contract matches these filters."
            : "No contracts yet. Upload a contracts file on the Uploads page."
        }
        filters={filters}
      />
    </Box>
  );
}
