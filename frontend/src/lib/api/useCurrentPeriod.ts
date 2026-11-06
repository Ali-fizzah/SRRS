"use client";

import { useQuery } from "@tanstack/react-query";

import { apiGet, type Schemas } from "@/lib/api/client";

type PeriodPage = { items: Schemas["PeriodOut"][] };

/** The current period (D6): the OPEN one, or the one being closed (§5.8 keeps it current). */
export function useCurrentPeriod() {
  return useQuery({
    queryKey: ["/periods", "current"],
    queryFn: async (): Promise<Schemas["PeriodOut"] | null> => {
      const open = await apiGet<PeriodPage>("/periods", { status: "OPEN", page_size: 1 });
      if (open.items[0]) return open.items[0];
      const closing = await apiGet<PeriodPage>("/periods", { status: "CLOSING", page_size: 1 });
      return closing.items[0] ?? null;
    },
  });
}
