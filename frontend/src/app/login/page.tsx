"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";

/** Login stub (P0-T6). Real sign-in with the JWT cookie arrives in P1-T3. */
export default function LoginPage() {
  const router = useRouter();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    router.push("/");
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
          <Stack component="form" spacing={2} onSubmit={handleSubmit}>
            <TextField
              label="Email"
              type="email"
              name="email"
              autoComplete="email"
              required
              fullWidth
            />
            <TextField
              label="Password"
              type="password"
              name="password"
              autoComplete="current-password"
              required
              fullWidth
            />
            <Button type="submit" variant="contained" size="large">
              Sign in
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
