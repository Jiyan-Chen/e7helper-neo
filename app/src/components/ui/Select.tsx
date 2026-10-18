import { Check, ChevronDown } from "lucide-react";
import { Select as S } from "radix-ui";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: string;
}

/** 下拉选择（枚举字段、模块选择等）。 */
export function Select({
  value, onChange, options, label, className, disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  label: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <S.Root value={value} onValueChange={onChange} disabled={disabled}>
      <S.Trigger aria-label={label} className={cn("field flex min-w-[140px] cursor-pointer items-center justify-between gap-3", className)}>
        <S.Value />
        <S.Icon>
          <ChevronDown className="size-4 text-gold" />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content position="popper" sideOffset={4} className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-gold-line/60 bg-[#151b2b] shadow-xl">
          <S.Viewport className="p-1">
            {options.map((o) => (
              <S.Item
                key={o.value}
                value={o.value}
                className="relative flex h-8 cursor-pointer select-none items-center rounded-md pl-8 pr-3 text-sm outline-none data-[highlighted]:bg-blue/40"
              >
                <S.ItemIndicator className="absolute left-2">
                  <Check className="size-4 text-gold" />
                </S.ItemIndicator>
                <S.ItemText>{o.label}</S.ItemText>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
}
