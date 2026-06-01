import { useEffect, useState } from "react";
import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";

import { fetchCurrentUser, logoutAccount } from "./api/auth";
import { setSessionToken } from "./api/client";
import { AdminModelSettingsPage } from "./admin/AdminModelSettingsPage";
import { AuthPage } from "./auth/AuthPage";
import { ProjectListPage } from "./projects/ProjectListPage";
import { ProjectWorkspace } from "./workspace/ProjectWorkspace";

const appTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#1677ff",
    colorBgLayout: "#f5f7fb",
    borderRadius: 12,
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  components: {
    Card: { borderRadiusLG: 16 },
    Button: { borderRadius: 10 },
    Input: { borderRadius: 10 },
  },
};

export function App() {
  const [user, setUser] = useState(null);
  const [project, setProject] = useState(null);
  const [view, setView] = useState("projects");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    restoreSession();
  }, []);

  async function restoreSession() {
    try {
      const payload = await fetchCurrentUser();
      setUser(payload.user);
    } catch {
      setSessionToken("");
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    try {
      await logoutAccount();
    } finally {
      setSessionToken("");
      setUser(null);
      setProject(null);
      setView("projects");
    }
  }

  function openProject(nextProject) {
    setProject(nextProject);
    setView("projects");
  }

  let content;

  if (loading) {
    content = <main className="app-auth-shell"><div className="auth-card">正在加载创作空间</div></main>;
  } else if (!user) {
    content = <AuthPage onAuthenticated={setUser} />;
  } else if (view === "admin" && user.role === "admin") {
    content = <AdminModelSettingsPage onBack={() => setView("projects")} />;
  } else if (project) {
    content = <ProjectWorkspace project={project} onBack={() => setProject(null)} />;
  } else {
    content = <ProjectListPage user={user} onOpenProject={openProject} onOpenAdmin={() => setView("admin")} onLogout={logout} />;
  }

  return <ConfigProvider locale={zhCN} theme={appTheme}>{content}</ConfigProvider>;
}
