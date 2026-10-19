// 流程和玩家模板的查询（B11）。
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "./api";
import { COMMON_PREFIX, type UserTemplate } from "./flow";
import { qk } from "./query";

export function useFlows() {
  return useQuery({ queryKey: qk.flows, queryFn: () => api().flows() });
}

/** 内置模板的备注很长（「大厅左侧「圣域」文字（可点区域含上方图标）」），只取括号前面那段。 */
export function shortNote(note: string | undefined): string {
  return (note ?? "").split(/[（(]/)[0].trim();
}

export function templateLabel(t: UserTemplate): string {
  return t.ref.startsWith(COMMON_PREFIX) ? shortNote(t.note) || t.name : t.name;
}

export function useTemplates() {
  const q = useQuery({ queryKey: qk.userTemplates, queryFn: () => api().userTemplates() });
  const byRef = useMemo(() => {
    const m = new Map<string, UserTemplate>();
    for (const t of [...(q.data?.mine ?? []), ...(q.data?.common ?? [])]) m.set(t.ref, t);
    return m;
  }, [q.data]);
  const label = (ref: string) => {
    const t = byRef.get(ref);
    if (t) return templateLabel(t);
    return ref.startsWith(COMMON_PREFIX) ? ref.slice(COMMON_PREFIX.length) : ref;
  };
  return { ...q, byRef, label };
}

/** 流程 id → 名字（运行记录、计划里显示用）。 */
export function useFlowNames(): Record<string, string> {
  const { data } = useFlows();
  return useMemo(() => Object.fromEntries((data ?? []).map((f) => [f.id, f.name])), [data]);
}
