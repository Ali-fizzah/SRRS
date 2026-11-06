"use client";

import CloseIcon from "@mui/icons-material/Close";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Typography from "@mui/material/Typography";
import type { GridColDef } from "@mui/x-data-grid";
import { useMemo, useState } from "react";

import { SourceLink } from "@/components/master/MasterPage";
import ServerDataGrid from "@/components/ServerDataGrid";
import type { Schemas } from "@/lib/api/client";

type Product = Schemas["ProductOut"];
type SspRule = Schemas["SspRuleOut"];

/** What an SSP rule says, as the API sent it: money stays a string, never a float (D1). */
function sspText(rule: Pick<Product, "ssp_source" | "ssp_value" | "ssp_pct">): string {
  if (rule.ssp_source === "FIXED") return `Fixed ${rule.ssp_value}`;
  if (rule.ssp_source === "PCT_OF_LIST") return `${rule.ssp_pct}% of list`;
  return rule.ssp_source === "LIST_PRICE" ? "List price" : "None";
}

const SSP_COLUMNS: GridColDef<SspRule>[] = [
  {
    field: "valid_from",
    headerName: "Valid from",
    width: 130,
    // A blank ssp_valid_from is stored as 1900-01-01: the rule applies from the beginning.
    valueFormatter: (value: string) => (value === "1900-01-01" ? "The beginning" : value),
  },
  {
    field: "valid_to",
    headerName: "Valid to",
    width: 120,
    sortable: false,
    valueFormatter: (value: string | null) => value ?? "Open",
  },
  {
    field: "ssp",
    headerName: "SSP",
    flex: 1,
    minWidth: 130,
    sortable: false,
    valueGetter: (_value, row) => sspText(row),
  },
  {
    field: "source",
    headerName: "Source",
    width: 170,
    sortable: false,
    renderCell: ({ row }) => <SourceLink upload={row.source_upload_id} row={row.source_row} />,
  },
];

function SspHistoryDrawer({ product, onClose }: { product: Product | null; onClose: () => void }) {
  return (
    <Drawer
      anchor="right"
      open={product !== null}
      onClose={onClose}
      sx={{ zIndex: (theme) => theme.zIndex.modal }}
      slotProps={{ paper: { sx: { width: { xs: "100%", sm: 640 }, p: 3 } } }}
    >
      {product && (
        <>
          <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, mb: 2 }}>
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
              <Typography variant="h2" component="h2" gutterBottom>
                SSP history
              </Typography>
              <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                {product.product_code}: {product.name}
              </Typography>
            </Box>
            <IconButton onClick={onClose} aria-label="Close SSP history">
              <CloseIcon />
            </IconButton>
          </Box>
          <ServerDataGrid<SspRule>
            path={`/products/${product.id}/ssp-history`}
            columns={SSP_COLUMNS}
            label="SSP history"
            emptyText="This product has no SSP rule."
          />
        </>
      )}
    </Drawer>
  );
}

export default function ProductsGrid() {
  const [selected, setSelected] = useState<Product | null>(null);

  const columns = useMemo<GridColDef<Product>[]>(
    () => [
      { field: "product_code", headerName: "Product code", width: 280 },
      { field: "name", headerName: "Name", width: 240 },
      { field: "category", headerName: "Category", width: 130 },
      {
        field: "list_price",
        headerName: "List price",
        width: 110,
        align: "right",
        headerAlign: "right",
      },
      { field: "recognition_method", headerName: "Recognition", width: 170 },
      {
        field: "is_separate_obligation",
        headerName: "Separate?",
        width: 100,
        valueFormatter: (value: boolean) => (value ? "Yes" : "No"),
      },
      { field: "revenue_account", headerName: "Revenue account", width: 150 },
      {
        field: "ssp",
        headerName: "Latest SSP",
        width: 140,
        sortable: false,
        valueGetter: (_value, row) => sspText(row),
      },
      {
        field: "source",
        headerName: "Source",
        width: 170,
        sortable: false,
        renderCell: ({ row }) => <SourceLink upload={row.source_upload_id} row={row.source_row} />,
      },
      {
        field: "actions",
        headerName: "",
        width: 130,
        sortable: false,
        disableColumnMenu: true,
        renderCell: ({ row }) => (
          <Button
            size="small"
            onClick={() => setSelected(row)}
            aria-label={`SSP history of ${row.product_code}`}
          >
            SSP history
          </Button>
        ),
      },
    ],
    [],
  );

  return (
    <>
      <ServerDataGrid<Product>
        path="/products"
        columns={columns}
        label="Products"
        emptyText="No products yet. Upload a products file to add them."
      />
      <SspHistoryDrawer product={selected} onClose={() => setSelected(null)} />
    </>
  );
}
