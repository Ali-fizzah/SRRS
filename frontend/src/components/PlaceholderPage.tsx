import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

type Props = {
  title: string;
  description: string;
  task: string;
  children?: ReactNode;
};

/** Stand-in for a page that a later task builds (P0-T6). */
export default function PlaceholderPage({ title, description, task, children }: Props) {
  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 2 }}>
        <Typography variant="h1">{title}</Typography>
        <Chip label={`Built in ${task}`} size="small" variant="outlined" />
      </Stack>
      <Card>
        <CardContent>
          <Typography color="text.secondary">{description}</Typography>
          {children}
        </CardContent>
      </Card>
    </Box>
  );
}
