"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { ApiError } from "@/lib/api/client";

/** TanStack Query for server state (CLAUDE.md). An expired session goes back to sign-in. */
export default function Providers({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [client] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error) => {
            if (error instanceof ApiError && error.status === 401) router.replace("/login");
          },
        }),
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: (failures, error) => !(error instanceof ApiError) && failures < 2,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
