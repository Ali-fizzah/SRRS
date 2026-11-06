import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import NextLink from "next/link";
import type { ReactNode } from "react";

/** Heading shared by the master data pages. Read-only for now (plan P1-T11). */
export default function MasterPage({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Stack spacing={2}>
      <div>
        <Typography variant="h1" gutterBottom>
          {title}
        </Typography>
        <Typography color="text.secondary">{description} Read-only for now.</Typography>
      </div>
      {children}
    </Stack>
  );
}

/** Link back to the upload a row came from (traceability, CLAUDE.md rule 5). */
export function SourceLink({ upload, row }: { upload: number | null; row: number | null }) {
  if (upload === null) return <>Not uploaded</>;
  return (
    <Link component={NextLink} href={`/uploads/${upload}`}>
      Upload {upload}, row {row}
    </Link>
  );
}
