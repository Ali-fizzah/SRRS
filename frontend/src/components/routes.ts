// Every route from plan §9. The nav and the placeholder pages both read this list,
// so a page's title and the task that builds it live in one place.

export type RouteInfo = {
  path: string;
  title: string;
  description: string;
  task: string;
};

export type NavSection = {
  heading?: string;
  routes: RouteInfo[];
};

export const NAV: NavSection[] = [
  {
    routes: [
      {
        path: "/",
        title: "Dashboard",
        description:
          "Current period, close checklist progress, recognised vs deferred, recent uploads.",
        task: "Phase 5",
      },
      {
        path: "/uploads",
        title: "Uploads",
        description: "Multi-file drag-and-drop upload, template downloads, upload history.",
        task: "P1-T10",
      },
      {
        path: "/contracts",
        title: "Contracts",
        description: "Contract list with filters.",
        task: "P2-T5",
      },
      {
        path: "/journals",
        title: "Journals",
        description: "Batches by period and status; approve, send back, post.",
        task: "P4-T5",
      },
      {
        path: "/periods",
        title: "Periods",
        description: "Period list, close workflow with live checklist, reopen (Admin).",
        task: "P5-T4",
      },
    ],
  },
  {
    heading: "Master data",
    routes: [
      {
        path: "/master-data/customers",
        title: "Customers",
        description: "Customer master data.",
        task: "P1-T11",
      },
      {
        path: "/master-data/products",
        title: "Products",
        description: "Products, recognition methods and SSP history.",
        task: "P1-T11",
      },
      {
        path: "/master-data/accounts",
        title: "GL accounts",
        description: "Chart of accounts.",
        task: "P1-T11",
      },
      {
        path: "/master-data/mappings",
        title: "GL mappings",
        description: "Account roles by product, category and default.",
        task: "P1-T11",
      },
    ],
  },
  {
    heading: "Reports",
    routes: [
      {
        path: "/reports/revenue-schedule",
        title: "Revenue schedule",
        description: "Recognised revenue per contract line per month.",
        task: "P5-T5",
      },
      {
        path: "/reports/deferred-rollforward",
        title: "Deferred rollforward",
        description: "Opening, billings, credit notes, recognised, closing.",
        task: "P5-T5",
      },
      {
        path: "/reports/trend",
        title: "Trend",
        description: "Monthly recognised revenue and deferred balance.",
        task: "P5-T5",
      },
      {
        path: "/reports/journal-register",
        title: "Journal register",
        description: "All entries by period, status and account.",
        task: "P5-T5",
      },
      {
        path: "/reports/gl-summary",
        title: "GL summary",
        description: "Debit, credit and net per account per period.",
        task: "P5-T5",
      },
      {
        path: "/reports/mrr-arr",
        title: "MRR / ARR",
        description: "Monthly and annual recurring revenue (non-GAAP).",
        task: "P5-T5",
      },
      {
        path: "/reports/close-status",
        title: "Close status",
        description: "State of each period and its checklist.",
        task: "P5-T5",
      },
    ],
  },
];

const BY_PATH = new Map(NAV.flatMap((s) => s.routes).map((r) => [r.path, r]));

export function routeInfo(path: string): RouteInfo {
  const info = BY_PATH.get(path);
  if (!info) throw new Error(`Unknown route ${path}`);
  return info;
}
