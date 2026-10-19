// 按 config_schema 自动生成的设置表单。每个字段一行（仿邮件列表），控件在右侧。
import { Plus, Settings2, Trash2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Check } from "@/components/ui/Check";
import { Select } from "@/components/ui/Select";
import { isDev } from "@/lib/env";
import type { FieldErrors } from "@/lib/hooks";
import { checkNumber, emptyItem, type Field } from "@/lib/schema";
import { cn } from "@/lib/utils";
import type { ModuleUI } from "@/modules/types";

export function ConfigForm({
  fields, config, update, errors, ui,
}: {
  fields: Field[];
  config: Record<string, unknown>;
  update: (key: string, value: unknown) => void;
  errors: FieldErrors;
  ui: ModuleUI;
}) {
  const locks = ui.fieldLocks?.(config) ?? {};
  // 被锁定的字段和设置不一致时（刚改了别的字段，或者旧设置）把锁定值写进设置
  const stale = Object.entries(locks).filter(([k, v]) => config[k] !== v);
  useEffect(() => {
    for (const [k, v] of stale) update(k, v);
  }, [JSON.stringify(stale)]); // eslint-disable-line react-hooks/exhaustive-deps -- 只在需要同步的内容变化时执行
  const visible = fields.filter(
    (f) => f.key !== "dry_run" && !ui.hiddenFields?.includes(f.key) && (isDev || !ui.devFields?.includes(f.key)),
  );
  // 附加选项画在主开关那一行里，不单独成行
  const shown = visible.filter((f) => !ui.subFields?.[f.key]);
  if (shown.length === 0) return <p className="py-2 text-sm text-muted">这个功能没有需要设置的选项。</p>;
  return (
    <div className="flex flex-col gap-2">
      {shown.map((f) => {
        const dep = ui.fieldDeps?.[f.key];
        const locked = f.key in locks;
        const off = (dep !== undefined && config[dep] === false) || locked;
        const value = locked ? locks[f.key] : config[f.key];
        const subs = visible.filter((s) => ui.subFields?.[s.key] === f.key);
        const Custom = ui.fieldRenderers?.[f.key];
        if (Custom) return <Custom key={f.key} field={f} value={value} onChange={(v) => update(f.key, v)} />;
        return (
          <FieldRow key={f.key} field={f} value={value} onChange={(v) => update(f.key, v)} error={errors[f.key]}
            disabled={off} ui={ui} devOnly={!!ui.devFields?.includes(f.key)}>
            {subs.map((s) => (
              <SubOption key={s.key} field={s} value={config[s.key]} onChange={(v) => update(s.key, v)}
                disabled={off || config[f.key] === false} />
            ))}
          </FieldRow>
        );
      })}
    </div>
  );
}

/** 附加选项（只支持布尔）：主开关说明下面的一个小勾选框，只写名字，不写说明。 */
function SubOption({
  field, value, onChange, disabled,
}: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled: boolean;
}) {
  return (
    <label className={cn("mt-2 flex w-fit items-center gap-2 text-sm", disabled ? "opacity-45" : "cursor-pointer")}>
      <Check checked={value === true} onChange={onChange} label={field.label} disabled={disabled} className="size-[22px] [&>svg]:size-4" />
      {field.label}
    </label>
  );
}

function FieldRow({
  field, value, onChange, error, disabled, ui, devOnly, children,
}: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  error?: string;
  disabled: boolean;
  ui: ModuleUI;
  devOnly: boolean;
  children?: ReactNode;
}) {
  const Icon = ui.fieldIcons?.[field.key] ?? Settings2;
  if (field.kind === "array" && field.children) {
    return <ArrayField field={field} value={Array.isArray(value) ? (value as Record<string, unknown>[]) : []} onChange={onChange} ui={ui} error={error} />;
  }
  return (
    <div className={cn("row-card", disabled && "opacity-45")}>
      <span className="medal">
        <Icon className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 font-bold">
          {field.label}
          {devOnly && <span className="rounded border border-gold-line px-1.5 text-[11px] font-normal text-gold">开发</span>}
        </div>
        {field.description && field.description !== field.label && <div className="text-xs text-muted">{field.description}</div>}
        {error && <div className="text-xs text-bad">{error}</div>}
        {children}
      </div>
      <span className="w-px self-stretch bg-white/10" />
      <Control field={field} value={value} onChange={onChange} disabled={disabled} error={error} />
    </div>
  );
}

function Control({
  field, value, onChange, disabled, error,
}: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  error?: string;
}) {
  switch (field.kind) {
    case "boolean":
      return <Check checked={value === true} onChange={onChange} label={field.label} disabled={disabled} />;
    case "enum":
      return (
        <Select value={String(value ?? field.default ?? "")} onChange={onChange} label={field.label} disabled={disabled}
          options={(field.enumValues ?? []).map((v) => ({ value: v, label: field.enumLabels?.[v] ?? v }))} />
      );
    case "integer":
    case "number":
      return <NumberInput field={field} value={value} onChange={onChange} disabled={disabled} error={error} />;
    case "string":
      return (
        <input className="field w-56" value={String(value ?? "")} disabled={disabled} aria-label={field.label}
          onChange={(e) => onChange(field.nullable && e.target.value === "" ? null : e.target.value)} />
      );
    default:
      return <span className="text-xs text-faint">不支持编辑</span>;
  }
}

/** 数字输入：输入过程中保留原文，合法时才提交。 */
function NumberInput({
  field, value, onChange, disabled, error, className,
}: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  error?: string;
  className?: string;
}) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  const [local, setLocal] = useState<string | null>(null);
  useEffect(() => setText(value === null || value === undefined ? "" : String(value)), [value]);
  const range =
    field.minimum !== undefined && field.maximum !== undefined ? `${field.minimum}–${field.maximum}`
      : field.minimum !== undefined ? `≥ ${field.minimum}` : field.maximum !== undefined ? `≤ ${field.maximum}` : "";
  return (
    <div className="flex flex-col items-end gap-0.5">
      <input
        className={cn("field num w-24 text-right text-base", className)}
        inputMode="numeric"
        value={text}
        disabled={disabled}
        aria-label={field.label}
        aria-invalid={!!(local || error)}
        placeholder={field.nullable ? "不限" : undefined}
        onChange={(e) => {
          const t = e.target.value.trim();
          setText(e.target.value);
          const problem = checkNumber(field, t);
          setLocal(problem);
          if (!problem) onChange(t === "" ? null : Number(t));
        }}
      />
      <span className={cn("text-[11px]", local ? "text-bad" : "text-faint")}>{local ?? range}</span>
    </div>
  );
}

/** 对象数组：表格，每行一项。 */
function ArrayField({
  field, value, onChange, ui, error,
}: {
  field: Field;
  value: Record<string, unknown>[];
  onChange: (v: unknown) => void;
  ui: ModuleUI;
  error?: string;
}) {
  const cols = (field.children ?? []).filter((c) => isDev || !ui.devSubFields?.includes(`${field.key}.${c.key}`));
  const setItem = (i: number, key: string, v: unknown) => onChange(value.map((it, j) => (j === i ? { ...it, [key]: v } : it)));
  return (
    <div className="row-card flex-col items-stretch gap-3">
      <div>
        <div className="font-bold">{field.label}</div>
        {field.description && <div className="text-xs text-muted">{field.description}</div>}
        {error && <div className="text-xs text-bad">{error}</div>}
      </div>
      <table className="w-full border-separate border-spacing-y-1 text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            {cols.map((c) => (
              <th key={c.key} className="px-1 font-normal" title={c.description}>{c.label}</th>
            ))}
            <th className="w-10" />
          </tr>
        </thead>
        <tbody>
          {value.map((item, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c.key} className="px-1">
                  {c.kind === "integer" || c.kind === "number" ? (
                    <NumberInput field={c} value={item[c.key]} onChange={(v) => setItem(i, c.key, v)} className="w-32" />
                  ) : c.kind === "boolean" ? (
                    <Check checked={item[c.key] === true} onChange={(v) => setItem(i, c.key, v)} label={c.label} />
                  ) : (
                    <input className="field w-full" value={String(item[c.key] ?? "")} aria-label={c.label}
                      onChange={(e) => setItem(i, c.key, c.nullable && e.target.value === "" ? null : e.target.value)} />
                  )}
                </td>
              ))}
              <td className="px-1 align-top">
                <button type="button" className="grid size-[34px] cursor-pointer place-items-center rounded-lg text-muted hover:bg-white/8 hover:text-bad"
                  aria-label="删除这一项" title="删除这一项" onClick={() => onChange(value.filter((_, j) => j !== i))}>
                  <Trash2 className="size-4" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange([...value, emptyItem(field.children ?? [])])}>
          <Plus className="size-4" />添加一项
        </button>
      </div>
    </div>
  );
}
