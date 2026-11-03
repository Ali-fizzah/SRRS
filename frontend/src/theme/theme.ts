"use client";

import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1f4e79" },
    secondary: { main: "#2e7d6b" },
    background: { default: "#f5f7fa" },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    h1: { fontSize: "1.75rem", fontWeight: 600 },
    h2: { fontSize: "1.375rem", fontWeight: 600 },
  },
  components: {
    MuiAppBar: { defaultProps: { elevation: 0 } },
    MuiCard: { defaultProps: { variant: "outlined" } },
  },
});

export default theme;
