# Ant Design Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the visible React app, especially the project canvas workspace, to a light Ant Design one-frame workbench while preserving existing business behavior.

**Architecture:** Add Ant Design at the app boundary, then migrate visible app shells and workspace render components from custom dark UI classes to Ant Design components. Keep controllers, API clients, polling, and canvas pointer behavior intact; most work is component markup and scoped CSS/token replacement.

**Tech Stack:** React 19, Vite 6, Ant Design, lucide-react icons, existing FastAPI backend.

---

## File Structure

- Modify `frontend/package.json` — add `antd` dependency.
- Modify `frontend/src/main.jsx` — import Ant Design reset stylesheet.
- Modify `frontend/src/App.jsx` — wrap the app with `ConfigProvider` and a light theme.
- Modify `frontend/src/auth/AuthPage.jsx` — convert auth form to Ant Design `Card`, `Form`, `Input`, `Button`, and `Alert`.
- Modify `frontend/src/projects/ProjectListPage.jsx` — convert project list/create page to Ant Design `Layout`, `Card`, `Form`, `Input`, `Button`, `List`, and `Empty`.
- Modify `frontend/src/admin/AdminModelSettingsPage.jsx` — convert admin settings shell/cards/forms to Ant Design components while preserving existing settings logic.
- Modify `frontend/src/account/AccountCreditsPanel.jsx` — convert credits display to Ant Design `Tag`/`Space`.
- Modify `frontend/src/workspace/ProjectWorkspace.jsx` — make one unified Ant Design workbench card containing header, tabs, canvas tab, and asset tab.
- Modify `frontend/src/workspace/AssetGallery.jsx` — convert asset gallery and generation history to Ant Design `Card`, `Segmented`, `Tag`, `Empty`, and `List`.
- Modify `frontend/src/workspace/CanvasWorkspaceComponents.jsx` — convert command panel, toolbar, inspector, production tray, and common dialogs/actions to Ant Design components without changing handlers.
- Modify `frontend/src/workspace/canvas-layout.css` — replace dark three-panel layout with light unified workbench grid styles.
- Modify `frontend/src/workspace/canvas-stage.css` — restyle the canvas grid, toolbar, node cards, and selection states for light mode.
- Modify `frontend/src/workspace/studio-polish.css` — remove or override dark studio polish rules that conflict with Ant Design light surfaces.
- Leave backend files unchanged.

## Constraints

- Do not run automated tests unless the user explicitly asks. This project has a user preference to avoid default test runs.
- Use `npm run build` as the default frontend verification command after implementation because it validates Vite compilation without running tests.
- This directory is not a git repository, so commit steps are replaced with checkpoint notes.
- Preserve all existing handler names and state shapes in controller/view props.

---

### Task 1: Install Ant Design and add global provider

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Add the Ant Design dependency**

Edit `frontend/package.json` and add `antd` to `dependencies`:

```json
{
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "antd": "^5.27.0",
    "vite": "^6.0.0",
    "typescript": "^5.7.2",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "lucide-react": "^0.468.0"
  }
}
```

- [ ] **Step 2: Install dependencies**

Run:

```bash
npm install
```

Expected: `node_modules` and lockfile update successfully; no package resolution errors.

- [ ] **Step 3: Import Ant Design reset CSS**

Modify `frontend/src/main.jsx` so it imports reset CSS before app styles:

```jsx
import React from "react";
import { createRoot } from "react-dom/client";
import "antd/dist/reset.css";
import { App } from "./App.jsx";
import "./image.css";
import "./app.css";

createRoot(document.getElementById("root")).render(<App />);
```

- [ ] **Step 4: Wrap the app with ConfigProvider**

Modify `frontend/src/App.jsx` imports:

```jsx
import { useEffect, useState } from "react";
import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
```

Add this theme object above `export function App()`:

```jsx
const appTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#1677ff",
    colorBgLayout: "#f5f7fb",
    borderRadius: 12,
    fontFamily:
      "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  components: {
    Card: {
      borderRadiusLG: 16,
    },
    Button: {
      borderRadius: 10,
    },
    Input: {
      borderRadius: 10,
    },
  },
};
```

Wrap all current `App` return branches by replacing the function body return logic with a single provider wrapper:

```jsx
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

  return (
    <ConfigProvider locale={zhCN} theme={appTheme}>
      {content}
    </ConfigProvider>
  );
}
```

- [ ] **Step 5: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Vite build completes. If it fails because `antd` is not installed, rerun `npm install` and rebuild.

---

### Task 2: Convert auth and project list shells to Ant Design light surfaces

**Files:**
- Modify: `frontend/src/auth/AuthPage.jsx`
- Modify: `frontend/src/projects/ProjectListPage.jsx`
- Modify: `frontend/src/app-core.css`

- [ ] **Step 1: Convert AuthPage imports**

Replace imports at the top of `frontend/src/auth/AuthPage.jsx` with:

```jsx
import { useState } from "react";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LogIn } from "lucide-react";

import { loginAccount, registerAccount } from "../api/auth";
```

- [ ] **Step 2: Replace AuthPage JSX with Ant Design components**

Keep state and `submit`/`updateField` unchanged. Replace the `return` block with:

```jsx
return (
  <main className="app-auth-shell app-light-shell">
    <Card className="auth-card app-light-card">
      <Form layout="vertical" onSubmitCapture={submit} requiredMark={false}>
        <div className="auth-icon"><LogIn size={24} /></div>
        <Typography.Title level={1}>{mode === "register" ? "创建账号" : "登录创作空间"}</Typography.Title>
        <Typography.Paragraph type="secondary">管理项目、图片生成和视频生成任务。</Typography.Paragraph>
        <Form.Item label="用户名">
          <Input value={form.username} onChange={(event) => updateField("username", event.target.value)} autoComplete="username" />
        </Form.Item>
        {mode === "register" ? (
          <Form.Item label="邮箱">
            <Input value={form.email} onChange={(event) => updateField("email", event.target.value)} autoComplete="email" />
          </Form.Item>
        ) : null}
        <Form.Item label="密码">
          <Input.Password type="password" value={form.password} onChange={(event) => updateField("password", event.target.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} />
        </Form.Item>
        {status ? <Alert type="error" showIcon message={status} role="alert" /> : null}
        <Button type="primary" htmlType="submit" block loading={submitting} disabled={!form.username.trim() || !form.password.trim() || (mode === "register" && !form.email.trim())}>
          {mode === "register" ? "注册并进入" : "登录"}
        </Button>
        <Button type="link" block onClick={() => setMode(mode === "register" ? "login" : "register")}>
          {mode === "register" ? "已有账号？去登录" : "没有账号？创建一个"}
        </Button>
      </Form>
    </Card>
  </main>
);
```

- [ ] **Step 3: Convert ProjectListPage imports**

Replace imports at the top of `frontend/src/projects/ProjectListPage.jsx` with:

```jsx
import { useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, Layout, List, Space, Typography } from "antd";
import { FolderPlus, LogOut, SlidersHorizontal } from "lucide-react";

import { createProject, fetchProjects } from "../api/projects";
```

- [ ] **Step 4: Replace ProjectListPage JSX**

Keep state and functions unchanged. Replace the `return` block with:

```jsx
return (
  <Layout className="project-shell app-light-shell">
    <section className="project-page-shell">
      <Card className="project-topbar app-light-card">
        <Space align="center" className="project-topbar-content">
          <div>
            <Typography.Title level={1}>Flow 创作项目</Typography.Title>
            <Typography.Text type="secondary">欢迎，{user.username}</Typography.Text>
          </div>
        </Space>
        <Space wrap>
          {user.role === "admin" ? <Button icon={<SlidersHorizontal size={17} />} onClick={onOpenAdmin}>模型配置</Button> : null}
          <Button icon={<LogOut size={17} />} onClick={onLogout}>退出</Button>
        </Space>
      </Card>

      <Card className="project-create-card app-light-card">
        <Form layout="inline" onSubmitCapture={submit} className="project-create-form">
          <Form.Item className="project-create-input">
            <Input prefix={<FolderPlus size={18} />} value={name} onChange={(event) => setName(event.target.value)} placeholder="新项目名称，例如：香水发布片" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" disabled={!name.trim()}>新增项目</Button>
          </Form.Item>
        </Form>
        {status ? <Alert type="error" showIcon message={status} role="alert" /> : null}
      </Card>

      <List
        className="project-list-grid"
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
        dataSource={projects}
        locale={{ emptyText: <Empty description="创建第一个项目后开始图片和视频生成。" /> }}
        renderItem={(project) => (
          <List.Item>
            <Card hoverable className="project-card app-light-card" onClick={() => onOpenProject(project)}>
              <Typography.Title level={4}>{project.name}</Typography.Title>
              <Typography.Text type="secondary">{new Date(project.updated_at).toLocaleString()}</Typography.Text>
            </Card>
          </List.Item>
        )}
      />
    </section>
  </Layout>
);
```

- [ ] **Step 5: Add light shell CSS**

Append this to `frontend/src/app-core.css`:

```css
.app-light-shell {
  min-height: 100vh;
  padding: clamp(18px, 3vw, 36px);
  color: #1f2937;
  background: #f5f7fb;
}

.app-light-card,
.auth-card.app-light-card,
.project-create-card.app-light-card,
.project-card.app-light-card,
.project-topbar.app-light-card {
  border: 1px solid #e5e7eb;
  color: #1f2937;
  background: #ffffff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
  backdrop-filter: none;
}

.app-light-card .ant-typography,
.app-light-card h1,
.app-light-card h2,
.app-light-card h3,
.app-light-card h4 {
  margin-top: 0;
  color: #111827;
}

.project-page-shell {
  display: grid;
  gap: 18px;
  width: min(1240px, 100%);
  margin: 0 auto;
}

.project-topbar-content {
  min-width: 0;
}

.project-topbar.app-light-card .ant-card-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.project-create-card.app-light-card {
  margin-bottom: 0;
}

.project-create-form {
  width: 100%;
}

.project-create-input {
  flex: 1 1 360px;
}

.project-list-grid .ant-list-item {
  height: 100%;
}

.project-list-grid .project-card {
  height: 100%;
}
```

- [ ] **Step 6: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds. If an Ant Design import is unused, remove the unused import and rebuild.

---

### Task 3: Convert account credits and admin settings surfaces

**Files:**
- Modify: `frontend/src/account/AccountCreditsPanel.jsx`
- Modify: `frontend/src/admin/AdminModelSettingsPage.jsx`
- Modify: `frontend/src/app-core.css`

- [ ] **Step 1: Replace AccountCreditsPanel implementation**

Replace `frontend/src/account/AccountCreditsPanel.jsx` with:

```jsx
import { Space, Tag, Tooltip } from "antd";
import { Coins } from "lucide-react";

const ACTION_LABELS = {
  project_image: "项目出图",
  project_image_edit: "项目修图",
  project_video: "项目视频",
  canvas_image: "画布出图",
  canvas_image_edit: "画布修图",
  canvas_image_batch: "画布批量图",
  canvas_video: "画布视频",
};

export function AccountCreditsPanel({ credits }) {
  const account = credits?.account;
  const costs = Array.isArray(credits?.costs) ? credits.costs : [];
  const quotas = new Map((credits?.quotas || []).map((quota) => [quota.action_type, quota]));

  return (
    <Space className="account-credits-panel" aria-label="账户积分" size={[6, 6]} wrap>
      <Tag color="blue" icon={<Coins size={14} />}>积分 {account?.balance ?? "--"}</Tag>
      {costs
        .filter((item) => item.action_type.startsWith("canvas_"))
        .map((item) => {
          const quota = quotas.get(item.action_type);
          const label = `${ACTION_LABELS[item.action_type] || item.action_type}: ${item.cost} 点${quota ? ` · ${quota.used_count}/${quota.limit_count}` : ""}`;
          return (
            <Tooltip title={label} key={item.action_type}>
              <Tag>{label}</Tag>
            </Tooltip>
          );
        })}
    </Space>
  );
}
```

- [ ] **Step 2: Convert AdminModelSettingsPage imports**

Replace imports at the top of `frontend/src/admin/AdminModelSettingsPage.jsx` with:

```jsx
import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Form, Input, Layout, Select, Space, Spin, Typography } from "antd";
import { ArrowLeft, Save, ShieldCheck } from "lucide-react";

import { fetchModelSettings, updateModelSettings } from "../api/admin";
```

- [ ] **Step 3: Replace AdminModelSettingsPage return block**

Replace the `return` block in `AdminModelSettingsPage` with:

```jsx
return (
  <Layout className="project-shell admin-settings-shell app-light-shell">
    <section className="project-page-shell">
      <Card className="project-topbar app-light-card">
        <div>
          <Typography.Title level={1}>模型配置</Typography.Title>
          <Typography.Text type="secondary">管理员可在这里配置 OpenAI 兼容图片、评估、提示词和视频模型</Typography.Text>
        </div>
        <Space wrap>
          <Button icon={<ArrowLeft size={17} />} onClick={onBack}>返回项目</Button>
          <Button type="primary" icon={<Save size={17} />} onClick={saveSettings} disabled={loading} loading={saving}>保存配置</Button>
        </Space>
      </Card>
      {status ? <Alert type={statusKind === "error" ? "error" : "success"} showIcon message={status} role="status" /> : null}
      {loading ? <Card className="app-light-card"><Spin /> 正在加载模型配置</Card> : null}
      {!loading ? (
        <section className="admin-settings-grid ant-admin-settings-grid">
          {FIELD_GROUPS.map((group) => (
            <Card className="admin-settings-card app-light-card" key={group.title} title={group.title} extra={<Typography.Text type="secondary">数据库覆盖值优先</Typography.Text>}>
              <Form layout="vertical" className="admin-field-grid">
                {group.fields.map((key) => renderField(key, settings[key], drafts[key], Boolean(cleared[key]), updateDraft, clearOverride))}
              </Form>
            </Card>
          ))}
        </section>
      ) : null}
    </section>
  </Layout>
);
```

- [ ] **Step 4: Replace admin render helpers with Ant Design fields**

Replace `renderField`, `SecretInput`, and `ValueInput` with:

```jsx
function renderField(key, entry = {}, draft = "", isCleared, onChange, onClear) {
  const fieldId = `admin-field-${key}`;
  return (
    <Form.Item
      className={isCleared ? "admin-field cleared" : "admin-field"}
      key={key}
      label={(
        <Space size={6}>
          <span>{FIELD_LABELS[key] || key}</span>
          <Typography.Text type="secondary"><ShieldCheck size={13} /> {entry.source || "unset"}</Typography.Text>
        </Space>
      )}
      extra={fieldMeta(entry, isCleared)}
    >
      <Space.Compact block>
        {entry.secret ? <SecretInput id={fieldId} entry={entry} /> : <ValueInput id={fieldId} fieldKey={key} value={draft} onChange={onChange} />}
        <Button onClick={() => onClear(key)}>使用环境默认</Button>
      </Space.Compact>
    </Form.Item>
  );
}

function SecretInput({ id, entry }) {
  const value = entry.configured ? `已通过环境变量配置：${entry.masked_value || "已隐藏"}` : "未配置，请在 .env 中设置";
  return <Input id={id} value={value} readOnly />;
}

function ValueInput({ id, fieldKey, value, onChange }) {
  if (BOOLEAN_FIELDS.has(fieldKey)) {
    return (
      <Select
        id={id}
        value={stringifyValue(value)}
        onChange={(nextValue) => onChange(fieldKey, nextValue)}
        options={[{ value: "true", label: "开启" }, { value: "false", label: "关闭" }]}
      />
    );
  }
  return <Input id={id} value={stringifyValue(value)} onChange={(event) => onChange(fieldKey, event.target.value)} />;
}
```

- [ ] **Step 5: Add admin light CSS**

Append to `frontend/src/app-core.css`:

```css
.ant-admin-settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
  gap: 16px;
}

.admin-settings-card .ant-card-head-title {
  color: #111827;
}

.admin-field .ant-form-item-extra {
  color: #6b7280;
}

.admin-field.cleared .ant-input,
.admin-field.cleared .ant-select-selector {
  border-color: #faad14 !important;
  background: #fffbe6 !important;
}
```

- [ ] **Step 6: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds.

---

### Task 4: Create unified Ant Design workbench frame in ProjectWorkspace

**Files:**
- Modify: `frontend/src/workspace/ProjectWorkspace.jsx`
- Modify: `frontend/src/workspace/canvas-layout.css`
- Modify: `frontend/src/workspace/studio-polish.css`

- [ ] **Step 1: Replace ProjectWorkspace imports**

Replace imports at the top of `frontend/src/workspace/ProjectWorkspace.jsx` with:

```jsx
import { useEffect, useRef, useState } from "react";
import { Button, Card, Layout, Space, Tabs, Tag, Typography } from "antd";
import { ArrowLeft, LayoutDashboard, Library } from "lucide-react";

import { fetchAccountCredits } from "../api/account";
import { fetchProjectAssets, fetchProjectTasks } from "../api/projects";
import { AccountCreditsPanel } from "../account/AccountCreditsPanel";
import { StatusPill } from "../image-optimizer/components/StatusPill";
import { AssetGallery } from "./AssetGallery";
import { CanvasWorkspace } from "./CanvasWorkspace";
```

- [ ] **Step 2: Replace tab key handling with Ant Design Tabs**

Remove `WORKSPACE_TABS`, `selectWorkspaceTab`, and `handleWorkspaceTabKeyDown`. Keep `tab` state.

Add this constant above the `return` statement inside `ProjectWorkspace`:

```jsx
const tabItems = [
  {
    key: "canvas",
    label: <span className="workspace-tab-label"><LayoutDashboard size={17} />画布生产</span>,
    children: <CanvasWorkspace projectId={project.id} assets={assets} onStatus={setStatus} onComplete={refreshProjectData} />,
  },
  {
    key: "assets",
    label: <span className="workspace-tab-label"><Library size={17} />媒体资产</span>,
    children: <AssetGallery assets={assets} tasks={tasks} />,
  },
];
```

- [ ] **Step 3: Replace ProjectWorkspace JSX with one workbench Card**

Replace the current `return` block with:

```jsx
return (
  <Layout className="image-only-shell workspace-light-shell">
    <section className="image-workbench workspace-ant-shell">
      <Card
        className="workspace-workbench-card"
        title={(
          <Space align="center" size={12} className="workspace-workbench-title">
            <Button icon={<ArrowLeft size={18} />} onClick={onBack} aria-label="返回项目列表" />
            <div>
              <Typography.Text className="workspace-eyebrow">Professional Creative Studio</Typography.Text>
              <Typography.Title level={2}>{project.name}</Typography.Title>
              <Typography.Text type="secondary">无限画布内完成文字出图、精选图片、图生视频和最终 JSON 提交</Typography.Text>
            </div>
          </Space>
        )}
        extra={(
          <Space wrap className="workspace-topbar-meta">
            <AccountCreditsPanel credits={credits} />
            <Tag>{assets.length} assets</Tag>
            <Tag>{tasks.length} tasks</Tag>
            <StatusPill status={status} />
          </Space>
        )}
      >
        <Tabs activeKey={tab} onChange={setTab} items={tabItems} className="workspace-ant-tabs" />
      </Card>
    </section>
  </Layout>
);
```

- [ ] **Step 4: Add unified workbench CSS**

Append to `frontend/src/workspace/canvas-layout.css`:

```css
.workspace-light-shell {
  min-height: 100vh;
  padding: clamp(16px, 2.2vw, 28px);
  background: #f5f7fb;
}

.workspace-ant-shell {
  width: min(1680px, 100%);
  margin: 0 auto;
}

.workspace-workbench-card {
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
}

.workspace-workbench-card > .ant-card-head {
  border-bottom: 1px solid #edf0f5;
  padding: 14px 20px;
}

.workspace-workbench-card > .ant-card-body {
  padding: 0 18px 18px;
}

.workspace-workbench-title .ant-typography {
  margin: 0;
}

.workspace-eyebrow {
  display: block;
  color: #1677ff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.workspace-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.workspace-ant-tabs > .ant-tabs-nav {
  margin-bottom: 16px;
}
```

- [ ] **Step 5: Neutralize old dark workspace polish**

Append to `frontend/src/workspace/studio-polish.css`:

```css
.workspace-light-shell.image-only-shell {
  background: #f5f7fb;
}

.workspace-light-shell .image-workbench {
  width: min(1680px, 100%);
}

.workspace-light-shell .workspace-tabs {
  display: none;
}
```

- [ ] **Step 6: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds and no `WORKSPACE_TABS` references remain.

---

### Task 5: Convert AssetGallery to Ant Design components

**Files:**
- Modify: `frontend/src/workspace/AssetGallery.jsx`
- Modify: `frontend/src/workspace/studio-polish.css`

- [ ] **Step 1: Replace AssetGallery imports**

Replace imports at the top of `frontend/src/workspace/AssetGallery.jsx` with:

```jsx
import { useMemo, useState } from "react";
import { Card, Empty, List, Segmented, Space, Tag, Typography } from "antd";
import { ImagePlus, Layers3, Video } from "lucide-react";

import { assetKindLabel, assetLabel, isImageAsset, isVideoAsset, safeDisplayUrl } from "./mediaUrls";
```

- [ ] **Step 2: Replace ReviewBadge**

Replace `ReviewBadge` with:

```jsx
function ReviewBadge({ status }) {
  const label = status === "approved" ? "已通过" : status === "rejected" ? "已拒绝" : "待审核";
  const color = status === "approved" ? "green" : status === "rejected" ? "red" : "gold";
  return <Tag color={color}>{label}</Tag>;
}
```

- [ ] **Step 3: Replace AssetGallery return block**

Keep `filter`, `counts`, and `visibleAssets` unchanged. Replace the `return` block with:

```jsx
return (
  <section className="asset-gallery asset-library-workspace ant-asset-gallery">
    <Card
      className="app-light-card"
      title={(
        <div>
          <Typography.Title level={4}>Media Library</Typography.Title>
          <Typography.Text type="secondary">图片和视频同属画布媒体资产，可进入 @引用、创作图谱和最终 JSON</Typography.Text>
        </div>
      )}
      extra={(
        <Segmented
          value={filter}
          onChange={setFilter}
          options={ASSET_FILTERS.map((item) => ({ label: `${item.label} ${counts[item.value]}`, value: item.value }))}
        />
      )}
    >
      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
        dataSource={visibleAssets}
        locale={{ emptyText: <Empty description={assets.length ? "当前过滤条件下没有资产。" : "上传媒体或生成结果后，素材会自动进入项目资产库。"} /> }}
        renderItem={(asset) => (
          <List.Item>
            <Card className="asset-card media-asset-card app-light-card" cover={<AssetPreview asset={asset} />}>
              <Card.Meta
                title={assetLabel(asset, assetKindLabel(asset))}
                description={(
                  <Space size={[4, 4]} wrap>
                    <Tag>{asset.media_type || "unknown media"}</Tag>
                    <ReviewBadge status={asset.review_status || "pending"} />
                  </Space>
                )}
              />
            </Card>
          </List.Item>
        )}
      />
    </Card>

    <Card className="app-light-card" title={<Space><Layers3 size={18} />Generation History</Space>} extra={<Tag>{tasks.length} 条记录</Tag>}>
      {tasks.length ? (
        <List
          className="compact-history-list"
          dataSource={tasks}
          renderItem={(task) => (
            <List.Item className={task.status === "failed" ? "task-failed" : ""}>
              <List.Item.Meta
                title={`${task.kind} · ${task.status}`}
                description={task.error || task.input?.prompt || task.input?.input || "生成任务"}
              />
              {task.charged_credits !== undefined && task.charged_credits !== null ? <Tag>{task.charged_credits} 积分</Tag> : null}
            </List.Item>
          )}
        />
      ) : (
        <Empty image={<Layers3 size={22} />} description="还没有生成任务；从图片工作区或画布提交后会在这里形成时间线。" />
      )}
    </Card>
  </section>
);
```

- [ ] **Step 4: Add AssetPreview helper**

Add this helper below `AssetGallery`:

```jsx
function AssetPreview({ asset }) {
  if (isImageAsset(asset) && safeDisplayUrl(asset.url)) {
    return <img className="asset-preview-media" src={safeDisplayUrl(asset.url)} alt="项目图片资产" loading="lazy" decoding="async" referrerPolicy="no-referrer" />;
  }
  if (isVideoAsset(asset) && safeDisplayUrl(asset.url)) {
    return <video className="asset-preview-media" src={safeDisplayUrl(asset.url)} controls preload="metadata" playsInline aria-label={`项目视频资产：${assetLabel(asset, "视频")}`} />;
  }
  return (
    <div className="asset-placeholder asset-preview-media">
      {isVideoAsset(asset) ? <Video size={30} /> : <ImagePlus size={30} />}
      <span>{assetKindLabel(asset)}资产</span>
    </div>
  );
}
```

- [ ] **Step 5: Add asset gallery CSS**

Append to `frontend/src/workspace/studio-polish.css`:

```css
.ant-asset-gallery {
  display: grid;
  gap: 16px;
  width: 100%;
}

.ant-asset-gallery .ant-card-head-title .ant-typography {
  margin: 0;
}

.asset-preview-media {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  background: #f3f4f6;
}

video.asset-preview-media {
  object-fit: contain;
}
```

- [ ] **Step 6: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds.

---

### Task 6: Convert CanvasWorkspaceView shell to Ant Design panels

**Files:**
- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- Modify: `frontend/src/workspace/canvas-layout.css`

- [ ] **Step 1: Add Ant Design imports**

Update the imports at the top of `frontend/src/workspace/CanvasWorkspaceComponents.jsx`:

```jsx
import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Empty, Input, Radio, Space, Tag, Typography } from "antd";
import { Check, Film, ImagePlus, Loader2, Maximize2, MousePointer2, Plus, RefreshCw, RotateCcw, Sparkles, UploadCloud, Video, X, ZoomIn, ZoomOut } from "lucide-react";
```

- [ ] **Step 2: Replace the top-level shell tags in CanvasWorkspaceView**

In `CanvasWorkspaceView`, keep all destructuring unchanged. Replace the opening command panel block:

```jsx
<section className="creative-canvas-shell">
  <aside className="canvas-command-panel">
```

with:

```jsx
<section className="creative-canvas-shell ant-creative-canvas-shell">
  <Card className="canvas-command-panel ant-canvas-panel" title="Creative Canvas" extra={<Tag color="blue">Tools</Tag>}>
```

Replace the closing `</aside>` after the media reference section with `</Card>`.

Replace:

```jsx
<div className="canvas-stage-shell">
```

with:

```jsx
<Card className="canvas-stage-shell ant-canvas-stage-card" styles={{ body: { padding: 0 } }}>
```

Replace its matching closing `</div>` after the production tray with `</Card>`.

Replace:

```jsx
<aside className="canvas-inspector-panel">
```

with:

```jsx
<Card className="canvas-inspector-panel ant-canvas-panel" title="Inspector">
```

Replace the inspector closing `</aside>` with `</Card>`.

- [ ] **Step 3: Convert brief input and primary command buttons**

Replace the plain `<textarea ... />` in `.canvas-brief-editor` with Ant Design `Input.TextArea`:

```jsx
<Input.TextArea ref={briefTextareaRef} value={brief} onChange={actions.handleBriefChange} onKeyDown={actions.handleBriefKeyDown} onKeyUp={actions.handleBriefCursor} onClick={actions.handleBriefCursor} onBlur={actions.closeMentionMenu} role="combobox" aria-autocomplete="list" aria-expanded={Boolean(mentionMenu)} aria-controls={mentionMenu ? "canvas-mention-listbox" : undefined} aria-activedescendant={mentionMenu ? `canvas-mention-option-${activeMentionIndex}` : undefined} aria-haspopup="listbox" aria-label="创意简报，输入 @ 可引用文件；可用上下箭头选择建议，Enter 或 Tab 插入" aria-describedby={mentionMenu ? "canvas-mention-status" : undefined} placeholder="输入专业创意简报：主体、场景、镜头、光线、材质、文字和限制条件… 输入 @ 可引用文件" autoSize={{ minRows: 7, maxRows: 12 }} />
```

Replace the three command buttons immediately after the warning with:

```jsx
<Space direction="vertical" className="canvas-action-stack" size={8}>
  <Button type="primary" block icon={creating ? <Loader2 className="spinning" size={18} /> : <Sparkles size={18} />} onClick={actions.addBriefNode} disabled={!brief.trim() || loading || creating}>放入画布</Button>
  <Button block icon={creating ? <Loader2 className="spinning" size={18} /> : <Film size={18} />} onClick={actions.addStoryboardNode} disabled={!brief.trim() || loading || creating}>创建分镜节点</Button>
  <Button block icon={creatingSemanticSkeleton ? <Loader2 className="spinning" size={18} /> : <Sparkles size={18} />} onClick={actions.materializeSemanticSkeleton} disabled={loading || creatingSemanticSkeleton || creating || !canvas?.nodes?.some((node) => node.type === "brief")}>初始化 LMM 语义生产骨架</Button>
</Space>
```

- [ ] **Step 4: Convert reference role grid to Radio.Group**

Replace `.canvas-reference-role-grid` with:

```jsx
<Radio.Group className="canvas-reference-role-grid ant-reference-role-grid" value={referenceRole} onChange={(event) => actions.setReferenceRole(event.target.value)} disabled={loading || creating || uploadingAssets}>
  <Space direction="vertical" size={8}>
    {referenceRoles.map((role) => (
      <Radio.Button value={role.value} key={role.value}>
        <strong>{role.label}</strong>
        <small>{role.help}</small>
      </Radio.Button>
    ))}
  </Space>
</Radio.Group>
```

Replace the reference instruction textarea with:

```jsx
<Input.TextArea className="canvas-reference-instruction" value={referenceInstruction} onChange={(event) => actions.setReferenceInstruction(event.target.value)} disabled={loading || creating || uploadingAssets} aria-label="媒体专业约束，可选" placeholder="可选：写给该媒体的专业约束，例如：只保留瓶身轮廓，或只参考镜头运动节奏。" autoSize={{ minRows: 3, maxRows: 6 }} />
```

- [ ] **Step 5: Convert empty inspector state**

Replace:

```jsx
{selectedNode ? <NodeInspector node={selectedNode} edges={canvas?.edges || []} assetById={assetById} updatingPromptProgram={updatingPromptProgram} onSavePromptProgram={actions.updatePromptProgramNode} /> : <p>选择节点查看 Prompt、参考资产和后续编译信息。</p>}
```

with:

```jsx
{selectedNode ? <NodeInspector node={selectedNode} edges={canvas?.edges || []} assetById={assetById} updatingPromptProgram={updatingPromptProgram} onSavePromptProgram={actions.updatePromptProgramNode} /> : <Empty description="选择节点查看 Prompt、参考资产和后续编译信息。" />}
```

- [ ] **Step 6: Add light canvas shell CSS**

Append to `frontend/src/workspace/canvas-layout.css`:

```css
.ant-creative-canvas-shell {
  grid-template-columns: minmax(280px, 320px) minmax(0, 1fr) minmax(280px, 340px);
  gap: 16px;
  width: 100%;
  min-height: min(760px, calc(100vh - 220px));
}

.ant-canvas-panel,
.ant-canvas-stage-card {
  border-color: #e5e7eb;
  background: #ffffff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.ant-canvas-panel > .ant-card-head,
.ant-canvas-stage-card > .ant-card-head {
  border-bottom-color: #edf0f5;
}

.ant-canvas-panel > .ant-card-body {
  display: grid;
  align-content: start;
  gap: 14px;
}

.canvas-action-stack {
  width: 100%;
}

.ant-reference-role-grid,
.ant-reference-role-grid .ant-space {
  width: 100%;
}

.ant-reference-role-grid .ant-radio-button-wrapper {
  display: grid;
  width: 100%;
  height: auto;
  min-height: 56px;
  border-radius: 10px !important;
  padding: 8px 10px;
  line-height: 1.3;
}

.ant-reference-role-grid .ant-radio-button-wrapper small {
  display: block;
  color: #6b7280;
  font-size: 12px;
}
```

- [ ] **Step 7: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds. If Ant Design `styles` prop is unsupported in installed version, replace `styles={{ body: { padding: 0 } }}` with `bodyStyle={{ padding: 0 }}`.

---

### Task 7: Restyle canvas stage and node cards for light Ant Design

**Files:**
- Modify: `frontend/src/workspace/canvas-stage.css`

- [ ] **Step 1: Replace stage shell colors**

Append this light-mode override block to `frontend/src/workspace/canvas-stage.css`:

```css
.workspace-light-shell .canvas-toolbar {
  border-bottom: 1px solid #edf0f5;
  background: #ffffff;
}

.workspace-light-shell .canvas-toolbar-title {
  color: #111827;
}

.workspace-light-shell .canvas-toolbar-title small {
  border-color: #d6e4ff;
  color: #1677ff;
  background: #f0f5ff;
}

.workspace-light-shell .canvas-zoom-controls button {
  border-color: #d9d9d9;
  color: #374151;
  background: #ffffff;
}

.workspace-light-shell .canvas-zoom-controls button:hover:not(:disabled) {
  border-color: #1677ff;
  color: #1677ff;
  background: #f0f5ff;
}

.workspace-light-shell .canvas-stage {
  min-height: 640px;
  background:
    radial-gradient(circle at 25% 18%, rgba(22, 119, 255, 0.08), transparent 28%),
    radial-gradient(circle at 78% 12%, rgba(114, 46, 209, 0.06), transparent 24%),
    #fbfdff;
}

.workspace-light-shell .canvas-grid-plane {
  background-image:
    linear-gradient(rgba(31, 41, 55, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(31, 41, 55, 0.07) 1px, transparent 1px);
  background-size: 48px 48px;
}
```

- [ ] **Step 2: Replace node card styling with light cards**

Append this node override block to `frontend/src/workspace/canvas-stage.css`:

```css
.workspace-light-shell .canvas-node-card {
  border: 1px solid #d9e2ec;
  border-radius: 14px;
  color: #111827;
  background: #ffffff;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.10);
}

.workspace-light-shell .canvas-node-card.in-scope {
  border-color: #91caff;
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.08), 0 12px 32px rgba(15, 23, 42, 0.10);
}

.workspace-light-shell .canvas-node-card.selected {
  border-color: #1677ff;
  box-shadow: 0 0 0 4px rgba(22, 119, 255, 0.14), 0 16px 38px rgba(15, 23, 42, 0.14);
}

.workspace-light-shell .canvas-node-card span {
  color: #1677ff;
  background: #f0f5ff;
}

.workspace-light-shell .canvas-node-card strong,
.workspace-light-shell .canvas-node-card h3,
.workspace-light-shell .canvas-node-card p {
  color: #111827;
}

.workspace-light-shell .canvas-node-card small,
.workspace-light-shell .canvas-node-card pre {
  color: #6b7280;
}

.workspace-light-shell .canvas-node-card.type-asset,
.workspace-light-shell .canvas-node-card.type-selected-image,
.workspace-light-shell .canvas-node-card.type-edited-image {
  border-color: #b7eb8f;
}

.workspace-light-shell .canvas-node-card.type-asset span,
.workspace-light-shell .canvas-node-card.type-selected-image span,
.workspace-light-shell .canvas-node-card.type-edited-image span {
  color: #389e0d;
  background: #f6ffed;
}

.workspace-light-shell .canvas-node-card.type-generated-video {
  border-color: #ffadd2;
}

.workspace-light-shell .canvas-node-card.type-generated-video span {
  color: #c41d7f;
  background: #fff0f6;
}

.workspace-light-shell .canvas-node-card.type-semantic-spec,
.workspace-light-shell .canvas-node-card.type-prompt-program,
.workspace-light-shell .canvas-node-card.type-evaluation,
.workspace-light-shell .canvas-node-card.type-final-json,
.workspace-light-shell .canvas-node-card.type-style-system,
.workspace-light-shell .canvas-node-card.type-repair-version {
  border-color: #d3adf7;
}

.workspace-light-shell .canvas-node-card.type-semantic-spec span,
.workspace-light-shell .canvas-node-card.type-prompt-program span,
.workspace-light-shell .canvas-node-card.type-evaluation span,
.workspace-light-shell .canvas-node-card.type-final-json span,
.workspace-light-shell .canvas-node-card.type-style-system span,
.workspace-light-shell .canvas-node-card.type-repair-version span {
  color: #722ed1;
  background: #f9f0ff;
}

.workspace-light-shell .canvas-node-card.type-scene,
.workspace-light-shell .canvas-node-card.type-shot,
.workspace-light-shell .canvas-node-card.type-series-frame {
  border-color: #ffe58f;
}

.workspace-light-shell .canvas-node-card.type-scene span,
.workspace-light-shell .canvas-node-card.type-shot span,
.workspace-light-shell .canvas-node-card.type-series-frame span {
  color: #d48806;
  background: #fffbe6;
}
```

- [ ] **Step 3: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds.

---

### Task 8: Convert production tray and inspector actions to Ant Design buttons/cards

**Files:**
- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- Modify: `frontend/src/workspace/canvas-layout.css`

- [ ] **Step 1: Wrap production tray sections in Ant Design Cards**

In `CanvasWorkspaceView`, replace:

```jsx
<section className="canvas-image-batch-studio">
```

with:

```jsx
<Card className="canvas-image-batch-studio production-card" size="small">
```

Replace its closing `</section>` with `</Card>`.

Replace:

```jsx
<section className="canvas-series-director">
```

with:

```jsx
<Card className="canvas-series-director production-card" size="small">
```

Replace its closing `</section>` with `</Card>`.

Replace:

```jsx
<section className="canvas-final-submit">
```

with:

```jsx
<Card className="canvas-final-submit production-card" size="small">
```

Replace its closing `</section>` with `</Card>`.

- [ ] **Step 2: Convert action button classes by adding Ant Design-compatible class support**

For production tray and inspector action buttons, keep existing class names for minimal diff, but update CSS in Step 3 to make `.primary-image-action` and `.secondary-image-action` look like Ant Design inside `.workspace-light-shell`.

Do not change handler logic or disabled expressions.

- [ ] **Step 3: Add production tray and button light CSS**

Append to `frontend/src/workspace/canvas-layout.css`:

```css
.workspace-light-shell .canvas-production-tray {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.8fr) minmax(260px, 0.8fr);
  gap: 14px;
  border-top: 1px solid #edf0f5;
  padding: 14px;
  background: #fafafa;
}

.workspace-light-shell .production-card {
  border-color: #e5e7eb;
  background: #ffffff;
}

.workspace-light-shell .canvas-production-heading span,
.workspace-light-shell .canvas-series-director > span,
.workspace-light-shell .canvas-final-submit > span {
  color: #111827;
  font-weight: 700;
}

.workspace-light-shell .primary-image-action,
.workspace-light-shell .secondary-image-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 36px;
  border-radius: 10px;
  padding: 7px 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.workspace-light-shell .primary-image-action {
  border: 1px solid #1677ff;
  color: #ffffff;
  background: #1677ff;
  box-shadow: 0 2px 0 rgba(5, 145, 255, 0.1);
}

.workspace-light-shell .primary-image-action:hover:not(:disabled) {
  border-color: #4096ff;
  background: #4096ff;
}

.workspace-light-shell .secondary-image-action {
  border: 1px solid #d9d9d9;
  color: #1f2937;
  background: #ffffff;
}

.workspace-light-shell .secondary-image-action:hover:not(:disabled) {
  border-color: #4096ff;
  color: #1677ff;
}

.workspace-light-shell .primary-image-action:disabled,
.workspace-light-shell .secondary-image-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
```

- [ ] **Step 4: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds.

---

### Task 9: Convert remaining custom dialogs to Ant Design modal surfaces where low risk

**Files:**
- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`

- [ ] **Step 1: Add Modal, Form, Select, InputNumber imports**

Extend the Ant Design import in `CanvasWorkspaceComponents.jsx`:

```jsx
import { Alert, Button, Card, Empty, Form, Input, InputNumber, Modal, Radio, Select, Space, Tag, Typography } from "antd";
```

- [ ] **Step 2: Identify dialog helper functions**

Search within `frontend/src/workspace/CanvasWorkspaceComponents.jsx` for these function names and convert only their outer shells first:

```text
ImageBatchDialog
BranchOperationDialog
MediaApprovalDialog
ImageEditDialog
VideoFromCandidateDialog
VideoRemixDialog
```

- [ ] **Step 3: Use this Modal pattern for each dialog**

For each dialog helper, replace the outer custom overlay markup with this pattern, preserving the existing form fields, props, and submit handler names:

```jsx
return (
  <Modal
    open
    title="对话框标题"
    onCancel={onClose}
    onOk={onSubmit}
    confirmLoading={Boolean(creating || busy)}
    okText="确认"
    cancelText="取消"
    destroyOnClose
  >
    {/* Move the existing dialog body content here without changing field state or handlers. */}
  </Modal>
);
```

Use exact titles:

```text
ImageBatchDialog -> 生成候选图
BranchOperationDialog -> 分支治理确认
MediaApprovalDialog -> 生产媒体审批
ImageEditDialog -> 编辑图片
VideoFromCandidateDialog -> 从候选图生成视频
VideoRemixDialog -> 调整视频 / 重新生成
```

If a dialog already contains multiple submit buttons with different meanings, keep its internal buttons and set `footer={null}` on the Modal:

```jsx
<Modal open title="对话框标题" onCancel={onClose} footer={null} destroyOnClose>
  {/* existing buttons stay inside */}
</Modal>
```

- [ ] **Step 4: Build checkpoint**

Run:

```bash
npm run build
```

Expected: Build succeeds. If any dialog conversion becomes risky because helper internals are tightly coupled, leave that dialog's body unchanged and only apply light CSS in the final polish task.

---

### Task 10: Final light-mode polish and responsive behavior

**Files:**
- Modify: `frontend/src/app-core.css`
- Modify: `frontend/src/app-responsive.css`
- Modify: `frontend/src/workspace/canvas-layout.css`
- Modify: `frontend/src/workspace/canvas-stage.css`
- Modify: `frontend/src/workspace/studio-polish.css`

- [ ] **Step 1: Add responsive workspace rules**

Append to `frontend/src/app-responsive.css`:

```css
@media (max-width: 1200px) {
  .ant-creative-canvas-shell {
    grid-template-columns: minmax(240px, 280px) minmax(0, 1fr);
  }

  .ant-creative-canvas-shell .canvas-inspector-panel {
    grid-column: 1 / -1;
  }

  .workspace-light-shell .canvas-production-tray {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .workspace-light-shell {
    padding: 10px;
  }

  .workspace-workbench-card > .ant-card-head {
    padding: 12px;
  }

  .workspace-workbench-card > .ant-card-body {
    padding: 0 10px 10px;
  }

  .ant-creative-canvas-shell {
    grid-template-columns: 1fr;
  }

  .workspace-light-shell .canvas-stage {
    min-height: 520px;
  }

  .project-topbar.app-light-card .ant-card-body {
    align-items: flex-start;
    flex-direction: column;
  }
}
```

- [ ] **Step 2: Remove conflicting dark backgrounds inside light shells**

Append to `frontend/src/workspace/studio-polish.css`:

```css
.workspace-light-shell .canvas-command-panel,
.workspace-light-shell .canvas-stage-shell,
.workspace-light-shell .canvas-inspector-panel,
.workspace-light-shell .canvas-image-batch-studio,
.workspace-light-shell .canvas-series-director,
.workspace-light-shell .canvas-final-submit {
  color: #1f2937;
  background: #ffffff;
  backdrop-filter: none;
}

.workspace-light-shell .canvas-panel-heading span,
.workspace-light-shell .canvas-inspector-panel > span,
.workspace-light-shell .canvas-reference-strip > span,
.workspace-light-shell .canvas-reference-heading > span {
  color: #1677ff;
}

.workspace-light-shell .canvas-reference-strip small,
.workspace-light-shell .canvas-inspector-panel p,
.workspace-light-shell .canvas-series-director p,
.workspace-light-shell .canvas-series-director small,
.workspace-light-shell .canvas-final-submit p,
.workspace-light-shell .canvas-final-submit small {
  color: #6b7280;
}
```

- [ ] **Step 3: Build verification**

Run:

```bash
npm run build
```

Expected: Build succeeds and outputs frontend assets to `frontend/dist`.

- [ ] **Step 4: Manual smoke verification**

Start the app if it is not already running:

```bash
USE_MOCK_IMAGES=true npm run dev
```

Expected:

```text
Uvicorn running on http://127.0.0.1:8000
VITE ... ready
```

Open the frontend URL shown by Vite and verify:

```text
- Login/auth screen uses light Ant Design card.
- Project list uses light Ant Design cards.
- Project workspace opens inside one large workbench card.
- Tabs are in the workbench header/body, not floating above the page.
- Canvas tab shows left tools, central light grid, right inspector, and bottom production tray inside one frame.
- Asset tab uses light Ant Design card/list styling.
- Existing major buttons are visible and disabled/enabled in the same situations as before.
```

- [ ] **Step 5: Checkpoint note**

Because this directory is not a git repository, do not run `git commit`. Record implementation completion in the final response with:

```text
Implemented Ant Design light workbench conversion. Verified with npm run build and manual app smoke check.
```

If `npm run build` or manual smoke fails, report the exact failure output instead of marking the work complete.

---

## Plan Self-Review

- Spec coverage: Tasks cover dependency setup, global light theme, app shell consistency, one-card workspace frame, left tools, central canvas stage, inspector, production tray, dialogs, asset tab, responsive behavior, and verification.
- Placeholder scan: No TBD/TODO placeholders remain. The dialog task contains an explicit fallback only for risky helper internals and still requires build verification.
- Type consistency: Existing component names and prop names match the current code: `ProjectWorkspace`, `CanvasWorkspace`, `CanvasWorkspaceView`, `AccountCreditsPanel`, `AssetGallery`, `StatusPill`, `CanvasWorkspaceController` props, and action names are preserved.
- Test policy: Automated test runs are intentionally omitted by default per user preference; `npm run build` and manual smoke are the default verification gates.
