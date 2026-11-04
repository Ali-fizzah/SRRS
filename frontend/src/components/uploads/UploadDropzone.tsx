"use client";

import UploadFileIcon from "@mui/icons-material/UploadFile";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { type DragEvent, useEffect, useRef, useState } from "react";

import StatusChip, { type UploadStatus } from "@/components/uploads/StatusChip";
import { apiGet, postUploads, type Schemas } from "@/lib/api/client";

type UploadResult = {
  upload_id: number;
  template: string;
  status: UploadStatus;
  total_rows: number;
  accepted_rows: number;
  rejected_rows: number;
};

/** Drag-and-drop upload (plan §9): post the files, then poll the job every 1.5 s (plan §10). */
export default function UploadDropzone() {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);

  const upload = useMutation({
    mutationFn: postUploads,
    onSuccess: () => {
      setFiles([]);
      void queryClient.invalidateQueries({ queryKey: ["/uploads"] });
    },
  });
  const accepted = upload.data;

  const job = useQuery({
    queryKey: ["job", accepted?.job_id],
    queryFn: () => apiGet<Schemas["JobOut"]>(`/jobs/${accepted?.job_id}`),
    enabled: accepted !== undefined,
    refetchInterval: (q) =>
      q.state.data?.status === "DONE" || q.state.data?.status === "FAILED" ? false : 1500,
  });
  const finished = job.data?.status === "DONE" || job.data?.status === "FAILED";

  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ queryKey: ["/uploads"] });
  }, [finished, queryClient]);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    setFiles((current) => [
      ...current.filter((f) => !incoming.some((n) => n.name === f.name)),
      ...incoming,
    ]);
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  }

  const results = (job.data?.result?.uploads ?? []) as UploadResult[];
  const nameOf = (id: number) =>
    accepted?.files.find((file) => file.upload_id === id)?.filename ?? `Upload ${id}`;

  return (
    <Card>
      <CardContent>
        <Typography variant="h2" gutterBottom>
          Upload files
        </Typography>
        <Box
          data-testid="dropzone"
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          sx={{
            border: "2px dashed",
            borderColor: dragging ? "primary.main" : "divider",
            bgcolor: dragging ? "action.hover" : "transparent",
            borderRadius: 1,
            p: 3,
            textAlign: "center",
          }}
        >
          <UploadFileIcon color="action" fontSize="large" aria-hidden />
          <Typography sx={{ mb: 1 }}>Drag .csv or .xlsx files here, or</Typography>
          <Button variant="outlined" onClick={() => input.current?.click()}>
            Choose files
          </Button>
          <input
            ref={input}
            id="upload-files"
            type="file"
            aria-label="Choose files to upload"
            accept=".csv,.xlsx"
            multiple
            hidden
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = ""; // choosing the same file again must still fire
            }}
          />
        </Box>

        {files.length > 0 && (
          <Stack spacing={1} sx={{ mt: 2 }}>
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
              {files.map((file) => (
                <Chip
                  key={file.name}
                  label={file.name}
                  onDelete={() => setFiles((list) => list.filter((f) => f !== file))}
                />
              ))}
            </Box>
            <Box>
              <Button
                variant="contained"
                disabled={upload.isPending}
                onClick={() => upload.mutate(files)}
              >
                {upload.isPending
                  ? "Sending…"
                  : `Upload ${files.length} file${files.length === 1 ? "" : "s"}`}
              </Button>
            </Box>
          </Stack>
        )}

        {upload.isError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {upload.error.message}
          </Alert>
        )}

        {accepted && !finished && (
          <Box sx={{ mt: 2 }} role="status">
            <Typography variant="body2" gutterBottom>
              Checking your files… {job.data?.progress ?? 0}%
            </Typography>
            <LinearProgress
              variant="determinate"
              value={job.data?.progress ?? 0}
              aria-label="Upload progress"
            />
          </Box>
        )}

        {job.data?.status === "FAILED" && (
          <Alert severity="error" sx={{ mt: 2 }}>
            The upload could not be processed: {job.data.error}
          </Alert>
        )}

        {job.data?.status === "DONE" && (
          <Stack spacing={1} sx={{ mt: 2 }} data-testid="upload-results">
            {results.map((result) => (
              <Box
                key={result.upload_id}
                sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}
              >
                <StatusChip status={result.status} />
                <Typography variant="body2" sx={{ flexGrow: 1 }}>
                  {nameOf(result.upload_id)}:{" "}
                  {result.total_rows === 0 && result.status === "REJECTED"
                    ? "the whole file was rejected"
                    : `${result.accepted_rows} of ${result.total_rows} rows accepted`}
                </Typography>
                <Button size="small" component={Link} href={`/uploads/${result.upload_id}`}>
                  {result.status === "ACCEPTED" ? "View" : "View errors"}
                </Button>
              </Box>
            ))}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
