"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useQuery } from "@tanstack/react-query";

import { apiGet, type Schemas } from "@/lib/api/client";

/** Blank templates with one example row (plan §7). */
export default function TemplateDownloads() {
  const templates = useQuery({
    queryKey: ["/templates"],
    queryFn: () => apiGet<Schemas["TemplateOut"][]>("/templates"),
    staleTime: Infinity,
  });

  return (
    <Card>
      <CardContent>
        <Typography variant="h2" gutterBottom>
          Templates
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          Each template has its headers and one example row. Replace the example with your data. Use
          the Excel version if your IDs have leading zeros.
        </Typography>
        {templates.isError && <Alert severity="error">{templates.error.message}</Alert>}
        {templates.isPending && <Skeleton variant="rounded" height={120} />}
        <Stack spacing={1}>
          {templates.data?.map((template) => (
            <Box
              key={template.name}
              sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}
            >
              <Typography sx={{ flexGrow: 1, minWidth: 140 }}>{template.title}</Typography>
              <Button
                size="small"
                variant="outlined"
                href={`/api/v1/templates/${template.name}`}
                aria-label={`Download ${template.title} template as CSV`}
              >
                CSV
              </Button>
              <Button
                size="small"
                variant="outlined"
                href={`/api/v1/templates/${template.name}?format=xlsx`}
                aria-label={`Download ${template.title} template as Excel`}
              >
                Excel
              </Button>
            </Box>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
