import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false },
  },
});

// 查询键集中放在这里，事件到来时按键失效
export const qk = {
  modules: ["modules"] as const,
  module: (id: string) => ["module", id] as const,
  timers: (id: string) => ["timers", id] as const,
  stats: (id: string) => ["stats", id] as const,
  history: (module?: string) => ["history", module ?? "*"] as const,
  schedules: ["schedules"] as const,
  instances: ["instances"] as const,
  flows: ["flows"] as const,
  flow: (id: string) => ["flows", id] as const,
  userTemplates: ["user-templates"] as const,
  heroes: ["heroes"] as const,
  heroDetail: (code: string) => ["heroes", code, "detail"] as const,
  heroBuilds: (code: string) => ["heroes", code, "builds"] as const,
};
