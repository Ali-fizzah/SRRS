import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import BatchesGrid from "@/components/journals/BatchesGrid";
import GenerateJournalsCard from "@/components/journals/GenerateJournalsCard";

export default function JournalsPage() {
  return (
    <Stack spacing={2}>
      <Typography variant="h1">Journals</Typography>
      <GenerateJournalsCard />
      <BatchesGrid />
    </Stack>
  );
}
