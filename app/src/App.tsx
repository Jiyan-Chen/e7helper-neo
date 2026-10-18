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
import { moduleUI, visibleModules } from "@/modules/registry";
import { CapturePage } from "@/pages/CapturePage";
import { HistoryPage } from "@/pages/HistoryPage";
import { LogsPage } from "@/pages/LogsPage";
import { SchedulesPage } from "@/pages/SchedulesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { StatsPage } from "@/pages/StatsPage";

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

function Shell() {
  const { data: modules } = useModules();
  const { pathname } = useLocation();
  useIdleScene();
  useEffect(() => {
    if (modules) setModuleNames(Object.fromEntries(modules.map((m) => [m.id, moduleUI(m.id).menuLabel ?? m.name])));
  }, [modules]);

  return (
    <div className="grid h-full min-w-[1100px] grid-rows-[60px_minmax(0,1fr)]">
      <TopBar />
      <div className="grid min-h-0 grid-cols-[200px_minmax(0,1fr)_auto]">
        <SideMenu />
        <main className="min-h-0 min-w-0">
          <Outlet />
        </main>
        {/* 模板采集页需要宽的画面，不显示右侧栏 */}
        {pathname !== "/capture" && <LivePanel />}
      </div>
    </div>
  );
}

function ModuleRoute() {
  const { id = "" } = useParams();
  return <ModulePage key={id} moduleId={id} />;
}

function Home() {
  const { data: modules } = useModules();
  if (!modules) return null;
  const first = visibleModules(modules)[0];
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
      { path: "stats", element: <StatsPage /> },
      { path: "logs", element: <LogsPage /> },
      { path: "settings", element: <SettingsPage /> },
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
