import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import TemplateDownloads from "@/components/uploads/TemplateDownloads";
import UploadDropzone from "@/components/uploads/UploadDropzone";
import UploadHistory from "@/components/uploads/UploadHistory";

export default function UploadsPage() {
  return (
    <Stack spacing={3}>
      <Typography variant="h1">Uploads</Typography>
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", md: "3fr 2fr" },
          alignItems: "start",
        }}
      >
        <UploadDropzone />
        <TemplateDownloads />
      </Box>
      <Box>
        <UploadHistory />
      </Box>
    </Stack>
  );
}
