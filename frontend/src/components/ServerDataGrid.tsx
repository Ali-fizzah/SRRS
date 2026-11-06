"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import {
  DataGrid,
  type GridColDef,
  type GridPaginationModel,
  type GridSortModel,
} from "@mui/x-data-grid";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { apiGet } from "@/lib/api/client";

type Page<T> = { items: T[]; total: number; page: number; page_size: number };

type Props<T extends { id: number }> = {
  /** API path of a §8 list endpoint, e.g. "/uploads". Also the query key to invalidate. */
  path: string;
  columns: GridColDef<T>[];
  label: string;
  emptyText: string;
  /** How often to refetch, given the rows on screen (false = do not). */
  refetchInterval?: (rows: T[]) => number | false;
  /** Grow rows to fit long text instead of cutting it off. */
  wrapText?: boolean;
  /** Filters sent to the API (plan §8). Changing them goes back to page 1. */
  filters?: Record<string, string | undefined>;
  /** Shown above the grid, from the same response, e.g. a total computed by the server. */
  renderSummary?: (data: Page<T> & Record<string, unknown>) => ReactNode;
};

/**
 * Data Grid with server-side paging and sorting (plan §4, §9): the community grid shows at most
 * 100 rows per page, so the API does the work and the grid only shows one page.
 */
export default function ServerDataGrid<T extends { id: number }>({
  path,
  columns,
  label,
  emptyText,
  refetchInterval,
  wrapText = false,
  filters,
  renderSummary,
}: Props<T>) {
  const [pagination, setPagination] = useState<GridPaginationModel>({ page: 0, pageSize: 25 });
  const [sortModel, setSortModel] = useState<GridSortModel>([]);
  const sort = sortModel[0]
    ? `${sortModel[0].sort === "desc" ? "-" : ""}${sortModel[0].field}`
    : undefined;

  // New filters start at page 1. Adjusting state during render sends one request, not two.
  const filterKey = JSON.stringify(filters ?? {});
  const [appliedFilterKey, setAppliedFilterKey] = useState(filterKey);
  if (filterKey !== appliedFilterKey) {
    setAppliedFilterKey(filterKey);
    setPagination((current) => ({ ...current, page: 0 }));
  }

  const query = useQuery({
    queryKey: [path, pagination.page, pagination.pageSize, sort, filterKey],
    queryFn: () =>
      apiGet<Page<T> & Record<string, unknown>>(path, {
        page: pagination.page + 1,
        page_size: pagination.pageSize,
        sort,
        ...filters,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => refetchInterval?.(q.state.data?.items ?? []) ?? false,
  });

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
      {query.isError && <Alert severity="error">{query.error.message}</Alert>}
      {query.data && renderSummary?.(query.data)}
      <DataGrid
        aria-label={label}
        rows={query.data?.items ?? []}
        rowCount={query.data?.total ?? 0}
        columns={columns}
        loading={query.isPending}
        paginationMode="server"
        paginationModel={pagination}
        onPaginationModelChange={setPagination}
        pageSizeOptions={[25, 50, 100]}
        sortingMode="server"
        sortModel={sortModel}
        onSortModelChange={(model) => {
          // A new order starts at page 1; changing both together sends one request, not two.
          setSortModel(model);
          setPagination((current) => ({ ...current, page: 0 }));
        }}
        disableColumnFilter
        disableRowSelectionOnClick
        localeText={{ noRowsLabel: emptyText }}
        getRowHeight={wrapText ? () => "auto" : undefined}
        sx={{
          minHeight: 220,
          bgcolor: "background.paper",
          ...(wrapText && {
            "& .MuiDataGrid-cell": { whiteSpace: "normal", wordBreak: "break-word", py: 1.5 },
          }),
        }}
      />
    </Box>
  );
}
