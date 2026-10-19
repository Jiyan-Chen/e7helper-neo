import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";
import type { Field } from "@/lib/schema";
import type { ModuleDetail, Trigger } from "@/lib/types";

/** 「计划」页里给玩家的一键添加（例如重复刷关的托管自动结算）。 */
export interface SchedulePreset {
  name: string;
  description: string;
  trigger: Trigger;
  /** 覆盖到模块当前设置上的字段 */
  config?: Record<string, unknown>;
}

/** 自己画的字段（代替自动表单里的那一行）。 */
export interface FieldRendererProps {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
}

export interface ModuleExtraProps {
  module: ModuleDetail;
  /** 当前（已保存的）设置 */
  config: Record<string, unknown>;
}

/**
 * 模块的界面扩展，放在 src/modules/<id>/index.tsx，默认导出，由 registry.ts 自动收集。
 * 没写的模块用通用页（自动表单 + 运行 + 最近运行）。
 */
export interface ModuleUI {
  id: string;
  icon: LucideIcon;
  /** 菜单顺序，小的在前 */
  order: number;
  /** 菜单里的短名字（默认用模块名） */
  menuLabel?: string;
  /** 只在开发版显示（示例模块） */
  devOnly?: boolean;
  /** 不在左侧菜单里单独出现（自定义流程的入口是「我的流程」页） */
  menuHidden?: boolean;
  /** 运行按钮上的字（默认「开始」） */
  runLabel?: string;
  fieldIcons?: Record<string, LucideIcon>;
  /** 字段 → 控制它的布尔字段：控制项关掉时这个字段变灰 */
  fieldDeps?: Record<string, string>;
  /** 附加选项（布尔字段 → 它所属的主开关）：画在主开关那一行里，只显示名字；主开关关掉时变灰 */
  subFields?: Record<string, string>;
  /** 自己画的字段：画在自动表单里这个字段的位置（例如书签刷取的商品选择） */
  fieldRenderers?: Record<string, ComponentType<FieldRendererProps>>;
  /** 永远不显示的字段（引擎内部参数已经用 SkipJsonSchema 隐藏，这里是额外的） */
  hiddenFields?: string[];
  /** 只在开发版显示的字段 */
  devFields?: string[];
  /** 数组字段里只在开发版显示的子字段，键是 "数组字段.子字段" */
  devSubFields?: string[];
  /** stats.json 的键 → 中文名（按这个顺序显示；没列出的不显示） */
  statLabels?: Record<string, string>;
  presets?: SchedulePreset[];
  /** 运行条左侧的附加控件（daily 的「持续收菜」） */
  RunExtra?: ComponentType<ModuleExtraProps>;
  /** 设置面板上方的附加内容 */
  Header?: ComponentType<ModuleExtraProps>;
  /** 设置保存后调用（daily 用它把新设置同步到「持续收菜」计划） */
  onConfigSaved?: (config: Record<string, unknown>) => void;
}
