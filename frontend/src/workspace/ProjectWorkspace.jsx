import { useEffect, useRef, useState } from "react";
import { Button, Card, Layout, Space, Tabs, Tag, Typography } from "antd";
import { ArrowLeft, LayoutDashboard, Library } from "lucide-react";

import { fetchAccountCredits } from "../api/account";
import { fetchProjectAssets, fetchProjectTasks } from "../api/projects";
import { AccountCreditsPanel } from "../account/AccountCreditsPanel";
import { StatusPill } from "../image-optimizer/components/StatusPill";
import { AssetGallery } from "./AssetGallery";
import { CanvasWorkspace } from "./CanvasWorkspace";

const PROJECT_DATA_REFRESH_FAILED_STATUS = { kind: "failed", message: "项目数据刷新失败，请稍后重试" };
const PROJECT_DATA_SYNCED_STATUS = { kind: "ready", message: "项目数据已同步" };

export function ProjectWorkspace({ project, onBack }) {
  const [tab, setTab] = useState("canvas");
  const [assets, setAssets] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [credits, setCredits] = useState(null);
  const [status, setStatus] = useState({ kind: "idle", message: "项目创作就绪" });
  const refreshRequestRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    refreshProjectData();
  }, [project.id]);

  async function refreshProjectData() {
    const requestId = refreshRequestRef.current + 1;
    refreshRequestRef.current = requestId;
    const [assetResult, taskResult, creditResult] = await Promise.allSettled([
      fetchProjectAssets(project.id),
      fetchProjectTasks(project.id),
      fetchAccountCredits(),
    ]);
    if (!mountedRef.current || requestId !== refreshRequestRef.current) {
      return;
    }
    if (assetResult.status === "fulfilled") {
      setAssets(assetResult.value.assets || []);
    }
    if (taskResult.status === "fulfilled") {
      setTasks(taskResult.value.tasks || []);
    }
    if (creditResult.status === "fulfilled") {
      setCredits(creditResult.value);
    }
    if (assetResult.status === "rejected" || taskResult.status === "rejected") {
      setStatus(PROJECT_DATA_REFRESH_FAILED_STATUS);
      return;
    }
    setStatus((currentStatus) => {
      if (currentStatus.kind === PROJECT_DATA_REFRESH_FAILED_STATUS.kind && currentStatus.message === PROJECT_DATA_REFRESH_FAILED_STATUS.message) {
        return PROJECT_DATA_SYNCED_STATUS;
      }
      return currentStatus;
    });
  }

  const tabItems = [
    {
      key: "canvas",
      label: (
        <span className="workspace-tab-label">
          <LayoutDashboard size={17} />
          画布生产
        </span>
      ),
      children: <CanvasWorkspace projectId={project.id} assets={assets} onStatus={setStatus} onComplete={refreshProjectData} />,
    },
    {
      key: "assets",
      label: (
        <span className="workspace-tab-label">
          <Library size={17} />
          媒体资产
        </span>
      ),
      children: <AssetGallery assets={assets} tasks={tasks} />,
    },
  ];

  return (
    <Layout className="image-only-shell workspace-light-shell">
      <section className="image-workbench workspace-ant-shell">
        <Card
          className="workspace-workbench-card"
          title={
            <Space className="workspace-workbench-title" size={12} align="center">
              <Button type="text" icon={<ArrowLeft size={18} />} onClick={onBack} aria-label="返回项目列表" />
              <Space direction="vertical" size={2}>
                <Typography.Text className="workspace-eyebrow">Professional Creative Studio</Typography.Text>
                <Typography.Title level={2}>{project.name}</Typography.Title>
                <Typography.Text type="secondary">无限画布内完成文字出图、精选图片、图生视频和最终 JSON 提交</Typography.Text>
              </Space>
            </Space>
          }
          extra={
            <Space wrap className="workspace-topbar-meta" size={8}>
              <AccountCreditsPanel credits={credits} />
              <Tag>{assets.length} assets</Tag>
              <Tag>{tasks.length} tasks</Tag>
              <StatusPill status={status} />
            </Space>
          }
        >
          <Tabs activeKey={tab} onChange={setTab} items={tabItems} className="workspace-ant-tabs" />
        </Card>
      </section>
    </Layout>
  );
}
