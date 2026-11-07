// 引擎 API 的数据形状（对照 engine/e7helper/api/，B08）。
// 时间字段有三种格式，统一用 lib/time.ts 的 toDate 解析：
// - unix 秒（number）：任务记录、日志、事件时间
// - 带时区的 ISO（UTC）：计划、模块计时
// - 不带时区的本地 ISO：模块自己的 history.jsonl / stats.json

export type TimeValue = number | string | null | undefined;

export interface DeviceInfo {
  connected: boolean;
  name?: string;
  resolution?: [number, number];
  backend?: string | null;
  index?: number | null;
  error?: string | null;
}

export type TaskStatus = "running" | "succeeded" | "failed" | "stopped" | "timeout" | "stuck";

export interface TaskRecord {
  id: string;
  module: string;
  source: string; // "api" / "ws" / "schedule:<id>"
  status: TaskStatus;
  started: number;
  config: Record<string, unknown>;
  ended: number | null;
  duration: number | null;
  error: string | null;
  debug_dir: string | null;
  timeout: number | null;
  elapsed?: number;
}

export interface Status {
  version: string;
  /** 这个版本带了哪些可选功能（正式版打包时可以不带 RTA）；旧引擎没有这个字段 */
  features?: { rta?: boolean };
  uptime: number;
  device: DeviceInfo;
  task: TaskRecord | null;
  assistants: { id: string; name: string }[];
  scheduler: { paused: boolean; schedules: number; next: { id: string; module: string; next_run: string } | null };
}

export interface ModuleInfo {
  id: string;
  name: string;
  kind: "task" | "assistant";
  description: string;
  has_routes: boolean;
  supports_next_due: boolean;
}

export interface ModuleDetail extends ModuleInfo {
  config_schema: JsonSchema;
  config: Record<string, unknown>;
}

export interface ModuleTimer {
  key: string;
  label: string;
  at: string | null;
  note: string;
}

export interface LogRecord {
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  name: string;
  message: string;
  time: number;
  thread?: string;
}

export type Trigger =
  | { type: "interval"; minutes: number }
  | { type: "daily"; at: string }
  | { type: "module"; min_interval_minutes: number };

export interface ScheduleSpec {
  module: string;
  name: string;
  enabled: boolean;
  trigger: Trigger;
  config: Record<string, unknown> | null;
  timeout: number | null;
  on_busy: "queue" | "skip";
  max_wait_minutes: number;
}

export interface ScheduleState {
  created: string;
  next_run: string | null;
  last_attempt: string | null;
  last_started: string | null;
  last_ended: string | null;
  last_status: string | null;
  last_task: string | null;
  last_success: string | null;
  last_skip: string | null;
  failures: number;
  queued_since: string | null;
  running_task: string | null;
}

export interface Schedule extends ScheduleSpec {
  id: string;
  module_name: string | null;
  state: ScheduleState;
}

export interface SchedulesSnapshot {
  paused: boolean;
  schedules: Schedule[];
}

export interface SceneInfo {
  scene: string | null;
  popup: string | null;
  obscured: boolean;
}

export interface Instances {
  root: string;
  version: string | null;
  instances: { index: number; name: string; android_version: string | null; started: boolean; adb: string | null }[];
}

// ---------------------------------------------------------------- JSON Schema（pydantic 生成的子集）

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  "x-enum-labels"?: Record<string, string>;
}

// ---------------------------------------------------------------- WebSocket

export type WsEvent =
  | { type: "event"; topic: "log"; time: number; data: LogRecord }
  | { type: "event"; topic: "task"; time: number; data: { module: string; status: TaskStatus; error?: string | null; duration?: number } }
  | { type: "event"; topic: "scene"; time: number; data: SceneInfo }
  | { type: "event"; topic: "device"; time: number; data: DeviceInfo }
  | { type: "event"; topic: "schedule"; time: number; data: { id?: string; module?: string; action: string; reason?: string; status?: string; next_run?: string | null } }
  | { type: "event"; topic: "stats"; time: number; data: { module: string; task: string } }
  | { type: "event"; topic: "assistant"; time: number; data: { module: string; state: string } }
  | { type: "event"; topic: string; time: number; data: unknown };

// ---------------------------------------------------------------- 模板采集（开发版）

export type Rect4 = [number, number, number, number];

export interface CaptureFrame {
  id: string;
  width: number;
  height: number;
  time: number;
}

export interface TemplateMetaJson {
  ref_size: [number, number];
  region: Rect4 | null;
  box: Rect4 | null;
  tap: Rect4 | null;
  threshold: number;
  grayscale: boolean;
  scales: number[];
  max_diff: number | null;
  note: string;
}

export interface CaptureTemplate {
  name: string;
  size?: [number, number];
  meta?: TemplateMetaJson;
  error?: string;
}

export interface CaptureSaveBody {
  frame: string;
  name: string;
  box: Rect4;
  region?: Rect4 | null;
  full?: boolean;
  margin?: number;
  tap?: Rect4 | null;
  threshold?: number;
  grayscale?: boolean;
  max_diff?: number | null;
  note?: string;
  overwrite?: boolean;
}

export interface CaptureHit {
  name: string;
  score?: number;
  diff?: number;
  rect?: Rect4;
  threshold?: number;
  max_diff?: number | null;
  hit?: boolean;
  ms?: number;
  error?: string;
}

export interface CaptureSaved {
  name: string;
  path: string;
  size: [number, number];
  meta: TemplateMetaJson;
  verify: { own: CaptureHit | null; other: CaptureHit | null };
}
