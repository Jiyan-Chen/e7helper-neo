import { create } from "zustand";
import { Dialog } from "./Dialog";

interface Ask {
  title: string;
  body: string;
  ok: string;
  danger: boolean;
  resolve: (v: boolean) => void;
}

const useAsk = create<{ ask: Ask | null }>(() => ({ ask: null }));

/** 游戏风确认框，返回用户是否确认。 */
export function confirmDialog(title: string, body: string, ok = "确定", danger = false): Promise<boolean> {
  return new Promise((resolve) => useAsk.setState({ ask: { title, body, ok, danger, resolve } }));
}

export function ConfirmHost() {
  const ask = useAsk((s) => s.ask);
  const done = (v: boolean) => {
    ask?.resolve(v);
    useAsk.setState({ ask: null });
  };
  return (
    <Dialog
      open={!!ask}
      onOpenChange={(v) => !v && done(false)}
      title={ask?.title ?? ""}
      className="w-[440px]"
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={() => done(false)}>取消</button>
          <button type="button" className={`btn ${ask?.danger ? "btn-real" : "btn-go"}`} onClick={() => done(true)}>{ask?.ok}</button>
        </>
      }
    >
      <p>{ask?.body}</p>
    </Dialog>
  );
}
