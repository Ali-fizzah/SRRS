import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import ContractsGrid from "@/components/contracts/ContractsGrid";
import RecognitionRunCard from "@/components/contracts/RecognitionRunCard";

export default function ContractsPage() {
  return (
    <Stack spacing={2}>
      <Typography variant="h1">Contracts</Typography>
      <RecognitionRunCard />
      <ContractsGrid />
    </Stack>
  );
}
