import { useEffect } from "react";
import { createHashRouter, Navigate, Outlet, RouterProvider, useLocation, useParams } from "react-router";
import { ModulePage } from "@/components/module/ModulePage";
import { LivePanel } from "@/components/shell/LivePanel";
import { SideMenu } from "@/components/shell/SideMenu";
import { TopBar } from "@/components/shell/TopBar";
import { ConfirmHost } from "@/components/ui/Confirm";
import { Toaster } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { isDev } from "@/lib/env";
import { useModules } from "@/lib/hooks";
import { setModuleNames } from "@/lib/labels";
import { useEngine } from "@/lib/store";
import { menuModules, moduleUI } from "@/modules/registry";
import { CapturePage } from "@/pages/CapturePage";
import { DraftPage } from "@/pages/DraftPage";
import { FlowEditorPage } from "@/pages/FlowEditorPage";
import { FlowsPage } from "@/pages/FlowsPage";
import { HeroesPage } from "@/pages/HeroesPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { LogsPage } from "@/pages/LogsPage";
import { SchedulesPage } from "@/pages/SchedulesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TemplatesPage } from "@/pages/TemplatesPage";

/** 空闲时每 10 秒识别一次当前画面（有任务时场景由任务的事件推送）。 */
function useIdleScene() {
  const connected = useEngine((s) => s.status?.device.connected ?? false);
  const running = useEngine((s) => !!s.status?.task);
  useEffect(() => {
    if (!connected || running) return;
    let alive = true;
    const poll = async () => {
      try {
        const s = await api().scene();
        if (alive) useEngine.setState({ scene: { scene: s.scene, popup: s.popup, obscured: s.obscured } });
      } catch {
        /* 截图失败时不更新 */
      }
    };
    void poll();
    const t = setInterval(poll, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [connected, running]);
}

/** 需要宽画面的页面（模板采集、流程编辑器、英雄图鉴、RTA 助手），不显示右侧栏。 */
const isWidePage = (path: string) =>
  path === "/capture" || path === "/templates" || path === "/heroes" || path === "/rta" || path.startsWith("/flows/");

function Shell() {
  const { data: modules } = useModules();
  const { pathname } = useLocation();
  useIdleScene();
  useEffect(() => {
    if (modules) setModuleNames(Object.fromEntries(modules.map((m) => [m.id, moduleUI(m.id).menuLabel ?? m.name])));
  }, [modules]);

  return (
    <div className="anim-fade grid h-full min-w-[1100px] grid-rows-[60px_minmax(0,1fr)]">
      <TopBar />
      <div className="grid min-h-0 grid-cols-[200px_minmax(0,1fr)_auto]">
        <SideMenu />
        <main className="min-h-0 min-w-0">
          {/* 换页时淡入（B12）。流程编辑器新建后会从 /flows/new 跳到 /flows/<id>，算同一页，不重新挂载 */}
          <div key={pathname.startsWith("/flows/") ? "/flows/edit" : pathname} className="anim-page h-full">
            <Outlet />
          </div>
        </main>
        {/* 模板采集页、流程编辑器、英雄图鉴、RTA 助手需要宽的画面，不显示右侧栏 */}
        {!isWidePage(pathname) && <LivePanel />}
      </div>
    </div>
  );
}

function ModuleRoute() {
  const { id = "" } = useParams();
  if (moduleUI(id).menuHidden) return <Navigate to="/flows" replace />;
  return <ModulePage key={id} moduleId={id} />;
}

function Home() {
  const { data: modules } = useModules();
  if (!modules) return null;
  const first = menuModules(modules)[0];
  return first ? <Navigate to={`/m/${first.id}`} replace /> : <Navigate to="/settings" replace />;
}

const router = createHashRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Home /> },
      { path: "m/:id", element: <ModuleRoute /> },
      { path: "schedules", element: <SchedulesPage /> },
      { path: "history", element: <HistoryPage /> },
      { path: "logs", element: <LogsPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "flows", element: <FlowsPage /> },
      { path: "flows/:id", element: <FlowEditorPage /> },
      { path: "templates", element: <TemplatesPage /> },
      { path: "heroes", element: <HeroesPage /> },
      { path: "rta", element: <DraftPage /> },
      ...(isDev ? [{ path: "capture", element: <CapturePage /> }] : []),
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export function App() {
  return (
    <>
      <RouterProvider router={router} />
      <Toaster />
      <ConfirmHost />
    </>
  );
}
