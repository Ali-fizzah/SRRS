import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import CloseWorkflow from "@/components/periods/CloseWorkflow";
import PeriodsGrid from "@/components/periods/PeriodsGrid";

export default function PeriodsPage() {
  return (
    <Stack spacing={2}>
      <Typography variant="h1">Periods</Typography>
      <CloseWorkflow />
      <PeriodsGrid />
    </Stack>
  );
}
