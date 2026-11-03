"use client";

import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import AssessmentIcon from "@mui/icons-material/Assessment";
import DashboardIcon from "@mui/icons-material/Dashboard";
import DescriptionIcon from "@mui/icons-material/Description";
import EventIcon from "@mui/icons-material/Event";
import LogoutIcon from "@mui/icons-material/Logout";
import MenuIcon from "@mui/icons-material/Menu";
import StorageIcon from "@mui/icons-material/Storage";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import { useTheme } from "@mui/material/styles";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { NAV } from "@/components/routes";

const DRAWER_WIDTH = 248;

function iconFor(path: string): ReactNode {
  if (path === "/") return <DashboardIcon />;
  if (path === "/uploads") return <UploadFileIcon />;
  if (path === "/contracts") return <DescriptionIcon />;
  if (path === "/journals") return <AccountBalanceIcon />;
  if (path === "/periods") return <EventIcon />;
  if (path.startsWith("/master-data")) return <StorageIcon />;
  return <AssessmentIcon />;
}

function isActive(pathname: string, path: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}

function NavList({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  return (
    <Box component="nav" aria-label="Main navigation">
      {NAV.map((section, i) => (
        <List
          key={section.heading ?? i}
          dense
          subheader={section.heading ? <ListSubheader>{section.heading}</ListSubheader> : undefined}
        >
          {section.routes.map((r) => (
            <ListItemButton
              key={r.path}
              component={Link}
              href={r.path}
              selected={isActive(pathname, r.path)}
              onClick={onNavigate}
            >
              <ListItemIcon sx={{ minWidth: 36 }}>{iconFor(r.path)}</ListItemIcon>
              <ListItemText primary={r.title} />
            </ListItemButton>
          ))}
        </List>
      ))}
    </Box>
  );
}

/** App layout: top bar + navigation drawer (permanent on desktop, toggled on tablet). */
export default function AppShell({ children }: { children: ReactNode }) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const paper = { "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" } };

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" sx={{ zIndex: theme.zIndex.drawer + 1 }}>
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            aria-label="Open navigation"
            onClick={() => setOpen(true)}
            sx={{ mr: 1, display: { lg: "none" } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }} noWrap>
            Revenue Recognition
          </Typography>
          <Tooltip title="Sign out">
            <IconButton color="inherit" component={Link} href="/login" aria-label="Sign out">
              <LogoutIcon />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      {/* CSS breakpoints (not useMediaQuery) so the server render already has the nav. */}
      <Drawer
        variant="temporary"
        open={open}
        onClose={() => setOpen(false)}
        sx={{ display: { xs: "block", lg: "none" }, ...paper }}
      >
        <Toolbar />
        <Divider />
        <NavList onNavigate={() => setOpen(false)} />
      </Drawer>
      <Drawer
        variant="permanent"
        open
        sx={{ display: { xs: "none", lg: "block" }, width: DRAWER_WIDTH, flexShrink: 0, ...paper }}
      >
        <Toolbar />
        <Divider />
        <NavList onNavigate={() => {}} />
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, md: 3 } }}>
        <Toolbar />
        {children}
      </Box>
    </Box>
  );
}
