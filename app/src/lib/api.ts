// REST 客户端。错误格式见 architecture.md「API 层」：{"error": {"code", "message", "detail"}}。
import type {
  CaptureFrame, CaptureHit, CaptureSaveBody, CaptureSaved, CaptureTemplate, Rect4,
  DeviceInfo, Instances, LogRecord, ModuleDetail, ModuleInfo, ModuleStats, ModuleTimer, Schedule,
  ScheduleSpec, SchedulesSnapshot, SceneInfo, Status, TaskRecord,
} from "./types";
import type { Flow, FlowSummary, UserTemplate } from "./flow";
import type { HeroBuilds, HeroDetail, HeroList, HeroUpdateResult } from "./heroes";

export interface UserTemplateSaveBody {
  frame: string;
  name: string;
  box: Rect4;
  tap?: Rect4 | null;
  moving: boolean;
  dim_check: boolean;
  threshold: number;
  note?: string;
  overwrite?: boolean;
}

export interface UserTemplateSaved extends UserTemplate {
  verify: { own: CaptureHit | null; other: CaptureHit | null };
  /** good = 认得清；ambiguous = 画面上还有很像的地方；weak = 原位置都认不出 */
  quality: "good" | "ambiguous" | "weak";
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public detail?: unknown) {
    super(message);
  }
}

export class Api {
  constructor(public readonly url: string, public readonly token: string | null) {}

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetch(this.url + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new ApiError(0, "network", "连不上引擎");
    }
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    const data = text ? JSON.parse(text) : undefined;
    if (!res.ok) {
      const err = data?.error;
      if (err) throw new ApiError(res.status, err.code, err.message, err.detail);
      // FastAPI 默认的请求体校验错误
      throw new ApiError(res.status, "http_" + res.status, typeof data?.detail === "string" ? data.detail : `请求失败（${res.status}）`, data?.detail);
    }
    return data as T;
  }

  get = <T>(path: string) => this.request<T>("GET", path);

  // 基础
  status = () => this.get<Status>("/api/status");
  logs = (limit = 300, level = "INFO") => this.get<LogRecord[]>(`/api/logs?limit=${limit}&level=${level}`);

  // 设备
  device = () => this.get<DeviceInfo>("/api/device");
  connect = (index?: number) => this.request<DeviceInfo>("POST", "/api/device/connect", index === undefined ? {} : { index });
  disconnect = () => this.request<DeviceInfo>("POST", "/api/device/disconnect");
  instances = () => this.get<Instances>("/api/device/instances");
  scene = () => this.get<SceneInfo & { clear: boolean; matches: string[] }>("/api/scene");
  screenshotUrl = (format: "png" | "jpeg" = "png") =>
    `${this.url}/api/device/screenshot?format=${format}${this.token ? `&token=${encodeURIComponent(this.token)}` : ""}`;

  // 模块
  modules = () => this.get<ModuleInfo[]>("/api/modules");
  module = (id: string) => this.get<ModuleDetail>(`/api/modules/${id}`);
  saveConfig = (id: string, config: Record<string, unknown>) =>
    this.request<Record<string, unknown>>("PUT", `/api/modules/${id}/config`, config);
  stats = (id: string, limit = 20) => this.get<ModuleStats>(`/api/modules/${id}/stats?limit=${limit}`);
  timers = (id: string) => this.get<ModuleTimer[]>(`/api/modules/${id}/timers`);

  // 任务
  startTask = (module: string, config?: Record<string, unknown>, timeout?: number) =>
    this.request<TaskRecord>("POST", "/api/tasks", { module, config, timeout });
  stopTask = () => this.request<{ stopped: boolean }>("POST", "/api/tasks/stop");
  currentTask = () => this.get<TaskRecord | null>("/api/tasks/current");
  history = (limit = 50, module?: string) =>
    this.get<TaskRecord[]>(`/api/tasks/history?limit=${limit}${module ? `&module=${module}` : ""}`);

  // 计划
  schedules = () => this.get<SchedulesSnapshot>("/api/schedules");
  createSchedule = (spec: Partial<ScheduleSpec> & Pick<ScheduleSpec, "module" | "trigger">) =>
    this.request<Schedule>("POST", "/api/schedules", spec);
  updateSchedule = (id: string, changes: Partial<ScheduleSpec>) => this.request<Schedule>("PATCH", `/api/schedules/${id}`, changes);
  deleteSchedule = (id: string) => this.request<void>("DELETE", `/api/schedules/${id}`);
  runSchedule = (id: string) => this.request<TaskRecord>("POST", `/api/schedules/${id}/run`);
  setSchedulerPaused = (paused: boolean) => this.request<SchedulesSnapshot>("PUT", "/api/scheduler", { paused });

  // 模板采集（开发版，B09）
  captureFreeze = () => this.request<CaptureFrame>("POST", "/api/capture/frames");
  async captureUpload(file: Blob): Promise<CaptureFrame> {
    const headers: Record<string, string> = { "Content-Type": "application/octet-stream" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const res = await fetch(`${this.url}/api/capture/frames/upload`, { method: "POST", headers, body: file });
    const data = await res.json();
    if (!res.ok) throw new ApiError(res.status, data?.error?.code ?? "upload_failed", data?.error?.message ?? "上传失败");
    return data;
  }
  captureFrameUrl = (id: string) => `${this.url}/api/capture/frames/${id}${this.tokenQuery()}`;
  captureStores = () => this.get<{ module: string; count: number }[]>("/api/capture/stores");
  captureTemplates = (module: string) => this.get<CaptureTemplate[]>(`/api/capture/templates?module=${encodeURIComponent(module)}`);
  captureTemplateUrl = (module: string, name: string, v = 0) =>
    `${this.url}/api/capture/templates/${module}/image/${name}${this.tokenQuery()}&v=${v}`;
  captureSave = (module: string, body: CaptureSaveBody) => this.request<CaptureSaved>("POST", `/api/capture/templates/${module}`, body);
  captureDelete = (module: string, name: string) => this.request<void>("DELETE", `/api/capture/templates/${module}/${name}`);
  captureMatch = (frame: string, module: string, names?: string[]) =>
    this.request<CaptureHit[]>("POST", "/api/capture/match", { frame, module, names });
  captureOcr = (frame: string, rect: Rect4 | null, mode: "read" | "line" | "number") =>
    this.request<{ results?: { text: string; score: number; rect: Rect4 }[]; number?: number | null; ms: number }>(
      "POST", "/api/capture/ocr", { frame, rect, mode });

  // 自定义流程 + 玩家模板（B11）
  flows = () => this.get<FlowSummary[]>("/api/flows");
  flow = (id: string) => this.get<Flow>(`/api/flows/${encodeURIComponent(id)}`);
  createFlow = (flow: Flow) => this.request<Flow>("POST", "/api/flows", flow);
  saveFlow = (id: string, flow: Flow) => this.request<Flow>("PUT", `/api/flows/${encodeURIComponent(id)}`, flow);
  copyFlow = (id: string) => this.request<Flow>("POST", `/api/flows/${encodeURIComponent(id)}/copy`);
  deleteFlow = (id: string, force = false) =>
    this.request<void>("DELETE", `/api/flows/${encodeURIComponent(id)}${force ? "?force=true" : ""}`);
  userTemplates = () => this.get<{ mine: UserTemplate[]; common: UserTemplate[] }>("/api/user-templates");
  userTemplateUrl = (ref: string, v = 0) =>
    `${this.url}/api/user-templates/image${this.tokenQuery()}&ref=${encodeURIComponent(ref)}&v=${v}`;
  saveUserTemplate = (body: UserTemplateSaveBody) => this.request<UserTemplateSaved>("POST", "/api/user-templates", body);
  deleteUserTemplate = (name: string, force = false) =>
    this.request<void>("DELETE", `/api/user-templates/${encodeURIComponent(name)}${force ? "?force=true" : ""}`);
  testTemplates = (templates: string[], frame?: string) =>
    this.request<{ frame: string | null; results: (CaptureHit & { ref: string })[] }>("POST", "/api/user-templates/test", { templates, frame });

  // 英雄图鉴（B13）
  heroes = () => this.get<HeroList>("/api/heroes");
  heroIconUrl = (code: string, v = "") => `${this.url}/api/heroes/${code}/icon${this.tokenQuery()}&v=${encodeURIComponent(v)}`;
  updateHeroes = () => this.request<HeroUpdateResult>("POST", "/api/heroes/update");
  heroDetail = (code: string) => this.get<HeroDetail>(`/api/heroes/${code}/detail`);
  heroBuilds = (code: string, refresh = false) => this.get<HeroBuilds>(`/api/heroes/${code}/builds${refresh ? "?refresh=true" : ""}`);
  heroAssetUrl = (name: string) => `${this.url}/api/hero-icons/${encodeURIComponent(name)}${this.tokenQuery()}`;
  artifactIconUrl = (code: string) => `${this.url}/api/artifacts/${encodeURIComponent(code)}/icon${this.tokenQuery()}`;

  private tokenQuery() {
    return this.token ? `?token=${encodeURIComponent(this.token)}` : "?";
  }

  wsUrl(path: string, params: Record<string, string | number> = {}) {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
    if (this.token) q.set("token", this.token);
    return this.url.replace(/^http/, "ws") + path + (q.size ? `?${q}` : "");
  }
}

let current: Api | null = null;

export function setApi(a: Api) {
  current = a;
}

/** 当前连接的客户端（连接建立之后才能调用）。 */
export function api(): Api {
  if (!current) throw new Error("引擎还没连接");
  return current;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
