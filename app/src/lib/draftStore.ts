// RTA 助手（B14e1）的当前局面和撤销记录。放在页面外面：切到别的页面再回来，选秀进度还在。
// 准备里的段位和先后手记在浏览器存储里（下次打开还是上次的）；开战规则每局随机，不记。
import { create } from "zustand";
import { DEFAULT_SETUP, UNKNOWN_RULE, gradeChoice, newDraft, type Draft, type Setup } from "./draft";

const SETUP_KEY = "e7helper.rta.setup";
const HISTORY = 200;

function loadSetup(): Setup {
  try {
    const s = JSON.parse(localStorage.getItem(SETUP_KEY) ?? "null");
    if (s && (s.side === "F" || s.side === "S") && Array.isArray(s.grades) && s.grades.length === 2) {
      return { side: s.side, grades: [gradeChoice(s.grades[0]), gradeChoice(s.grades[1])], rule: UNKNOWN_RULE };
    }
  } catch {
    /* 存储不可用时用默认值 */
  }
  return DEFAULT_SETUP;
}

function saveSetup(s: Setup) {
  try {
    localStorage.setItem(SETUP_KEY, JSON.stringify({ side: s.side, grades: s.grades }));
  } catch {
    /* 存不了就算了 */
  }
}

interface DraftStore {
  draft: Draft;
  /** 之前的局面，撤销时一个个退回去 */
  history: Draft[];
  /** 改局面；fn 原样返回（操作不合法）时不记 */
  apply: (fn: (d: Draft) => Draft) => void;
  undo: () => void;
  /** 下一局：回到准备，保留段位和先后手，开战规则回到不知道（也能撤销回去） */
  restart: () => void;
}

export const useDraft = create<DraftStore>((set, get) => ({
  draft: newDraft(loadSetup()),
  history: [],
  apply: (fn) => {
    const { draft, history } = get();
    const next = fn(draft);
    if (next === draft) return;
    if (next.setup !== draft.setup) saveSetup(next.setup);
    set({ draft: next, history: [...history, draft].slice(-HISTORY) });
  },
  undo: () => {
    const { history } = get();
    if (!history.length) return;
    set({ draft: history[history.length - 1], history: history.slice(0, -1) });
  },
  restart: () => get().apply((d) => newDraft({ ...d.setup, rule: UNKNOWN_RULE })),
}));
