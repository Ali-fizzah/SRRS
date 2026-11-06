import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

export type SimpleColumn<T> = {
  header: string;
  cell: (row: T) => ReactNode;
  align?: "right";
};

/** A short list that belongs to one contract, so it needs no paging. */
export default function SimpleTable<T>({
  label,
  columns,
  rows,
  rowKey,
  emptyText,
}: {
  label: string;
  columns: SimpleColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <Typography color="text.secondary">{emptyText}</Typography>;
  }
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label={label}>
        <TableHead>
          <TableRow>
            {columns.map((column) => (
              <TableCell key={column.header} align={column.align} sx={{ fontWeight: 600 }}>
                {column.header}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={rowKey(row)}>
              {columns.map((column) => (
                <TableCell key={column.header} align={column.align}>
                  {column.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
