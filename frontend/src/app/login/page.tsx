"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { signIn } from "@/lib/session";

/** Sign in (plan §9 /login). On success the API sets the session cookie (D11). */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Try again.");
      setBusy(false);
    }
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        p: 2,
        bgcolor: "background.default",
      }}
    >
      <Card sx={{ width: "100%", maxWidth: 400 }}>
        <CardContent>
          <Typography variant="h1" component="h1" gutterBottom>
            Sign in
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 3 }}>
            Revenue Recognition System
          </Typography>
          <Stack component="form" spacing={2} onSubmit={handleSubmit} noValidate>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              id="email"
              label="Email"
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              fullWidth
              autoFocus
            />
            <TextField
              id="password"
              label="Password"
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              fullWidth
            />
            <Button
              type="submit"
              variant="contained"
              size="large"
              disabled={busy || !email || !password}
            >
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
