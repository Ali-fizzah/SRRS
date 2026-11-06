"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import type { GridColDef } from "@mui/x-data-grid";
import { useQuery } from "@tanstack/react-query";
import NextLink from "next/link";
import { useMemo } from "react";

import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";
import { formatMoney, formatPeriod } from "@/lib/format";
import { fetchMe } from "@/lib/session";

type Line = Schemas["JournalLineOut"];

const MAY_OPEN_BATCH = new Set(["ACCOUNTANT", "APPROVER", "ADMIN"]); // plan §8 Journals: view

const blankIfZero = (value: string) => (Number(value) === 0 ? "" : formatMoney(value));

/** Every journal line of this contract, from any batch (plan §9). */
export default function JournalLinesTab({ id }: { id: string }) {
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: Infinity });
  const canOpenBatch = me.data?.roles.some((role) => MAY_OPEN_BATCH.has(role)) ?? false;

  const columns = useMemo<GridColDef<Line>[]>(
    () => [
      {
        field: "period_key",
        headerName: "Period",
        width: 100,
        valueFormatter: (value: string) => formatPeriod(value),
      },
      {
        field: "batch_no",
        headerName: "Batch",
        width: 90,
        sortable: false,
        renderCell: ({ row }) =>
          canOpenBatch ? (
            <Link component={NextLink} href={`/journals/${row.batch_id}`}>
              Batch {row.batch_no}
            </Link>
          ) : (
            `Batch ${row.batch_no}`
          ),
      },
      { field: "batch_status", headerName: "Status", width: 110, sortable: false },
      { field: "entry_type", headerName: "Type", width: 170 },
      {
        field: "account_code",
        headerName: "Account",
        flex: 1,
        minWidth: 200,
        valueGetter: (_value, row) => `${row.account_code} ${row.account_name}`,
      },
      {
        field: "debit",
        headerName: "Debit",
        width: 120,
        align: "right",
        headerAlign: "right",
        valueFormatter: blankIfZero,
      },
      {
        field: "credit",
        headerName: "Credit",
        width: 120,
        align: "right",
        headerAlign: "right",
        valueFormatter: blankIfZero,
      },
      { field: "description", headerName: "Description", flex: 1, minWidth: 200, sortable: false },
    ],
    [canOpenBatch],
  );

  return (
    <ServerDataGrid<Line>
      path={`/contracts/${id}/journal-lines`}
      columns={columns}
      label="Journal lines"
      emptyText="No journal lines yet. Use Generate journals on the Journals page."
      renderSummary={() => (
        <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            variant="outlined"
            size="small"
            href={`/api/v1/contracts/${id}/journal-lines?format=csv`}
          >
            Export CSV
          </Button>
        </Box>
      )}
    />
  );
}
