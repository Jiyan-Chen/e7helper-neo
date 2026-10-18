import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "./api";
import { qk } from "./query";
import type { ModuleDetail } from "./types";

/** 每隔 intervalMs 重新渲染一次（倒计时用）。 */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function useModules() {
  return useQuery({ queryKey: qk.modules, queryFn: () => api().modules(), staleTime: Infinity });
}

export function useModuleDetail(id: string) {
  return useQuery({ queryKey: qk.module(id), queryFn: () => api().module(id), staleTime: 60_000 });
}

export function useSchedules() {
  return useQuery({ queryKey: qk.schedules, queryFn: () => api().schedules(), refetchInterval: 30_000 });
}

export type FieldErrors = Record<string, string>;

/**
 * 模块设置的编辑：改动后 400ms 自动保存（PUT 整体替换）。
 * 返回的 config 是本地草稿；保存成功后用服务端补全后的结果覆盖。
 */
export function useConfigEditor(detail: ModuleDetail | undefined, onSaved?: (config: Record<string, unknown>) => void) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const moduleId = detail?.id;

  useEffect(() => {
    setDraft(detail ? { ...detail.config } : null);
    setErrors({});
    setState("idle");
  }, [moduleId]); // eslint-disable-line react-hooks/exhaustive-deps -- 只在切换模块时重置

  const save = useCallback(
    async (next: Record<string, unknown>) => {
      if (!moduleId) return;
      setState("saving");
      try {
        const saved = await api().saveConfig(moduleId, next);
        qc.setQueryData<ModuleDetail>(qk.module(moduleId), (old) => (old ? { ...old, config: saved } : old));
        setErrors({});
        setState("saved");
        onSaved?.(saved);
      } catch (e) {
        setState("error");
        if (e instanceof ApiError && Array.isArray(e.detail)) {
          const errs: FieldErrors = {};
          for (const d of e.detail as { loc: (string | number)[]; msg: string }[]) errs[String(d.loc[0])] = d.msg;
          setErrors(errs);
        }
        toast(`设置没有保存：${errorMessage(e)}`, "error");
      }
    },
    [moduleId, qc, onSaved],
  );

  const draftRef = useRef(draft);
  draftRef.current = draft;
  const update = useCallback(
    (key: string, value: unknown) => {
      const next = { ...(draftRef.current ?? {}), [key]: value };
      draftRef.current = next;
      setDraft(next);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void save(next), 400);
    },
    [save],
  );

  return { config: draft, update, errors, state };
}
