import { useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, Layout, List, Space, Typography } from "antd";
import { FolderPlus, LogOut, SlidersHorizontal } from "lucide-react";

import { createProject, fetchProjects } from "../api/projects";

export function ProjectListPage({ user, onOpenProject, onOpenAdmin, onLogout }) {
  const [projects, setProjects] = useState([]);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    loadProjects();
  }, []);

  async function loadProjects() {
    try {
      const payload = await fetchProjects();
      setProjects(payload.projects || []);
    } catch (error) {
      setStatus(error?.message || "项目加载失败");
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    try {
      const project = await createProject({ name: name.trim() });
      setName("");
      setProjects((current) => [project, ...current]);
      onOpenProject(project);
    } catch (error) {
      setStatus(error?.message || "项目创建失败");
    }
  }

  function handleProjectKeyDown(event, project) {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    onOpenProject(project);
  }

  return (
    <Layout className="project-shell app-light-shell">
      <section className="project-page-shell">
        <Card className="project-topbar app-light-card">
          <div>
            <Typography.Title level={1}>Flow 创作项目</Typography.Title>
            <Typography.Text type="secondary">欢迎，{user.username}</Typography.Text>
          </div>
          <Space wrap className="project-actions">
            {user.role === "admin" ? <Button type="default" icon={<SlidersHorizontal size={17} />} onClick={onOpenAdmin}>模型配置</Button> : null}
            <Button type="default" icon={<LogOut size={17} />} onClick={onLogout}>退出</Button>
          </Space>
        </Card>
        <Card className="project-create-card app-light-card">
          <Form className="project-create-form" layout="inline" onSubmitCapture={submit} requiredMark={false}>
            <FolderPlus size={22} />
            <Form.Item className="project-create-input">
              <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="新项目名称，例如：香水发布片" />
            </Form.Item>
            <Button type="primary" htmlType="submit" disabled={!name.trim()}>新增项目</Button>
          </Form>
          {status ? <Alert type="error" message={status} showIcon role="alert" /> : null}
        </Card>
        <List
          className="project-list-grid"
          grid={{ gutter: 20, xs: 1, sm: 2, md: 2, lg: 3, xl: 4, xxl: 4 }}
          dataSource={projects}
          locale={{ emptyText: <Empty description="创建第一个项目后开始图片和视频生成。" /> }}
          renderItem={(project) => (
            <List.Item key={project.id}>
              <Card
                className="project-card app-light-card"
                hoverable
                role="button"
                tabIndex={0}
                onClick={() => onOpenProject(project)}
                onKeyDown={(event) => handleProjectKeyDown(event, project)}
              >
                <Typography.Title level={4}>{project.name}</Typography.Title>
                <Typography.Text type="secondary">{new Date(project.updated_at).toLocaleString()}</Typography.Text>
              </Card>
            </List.Item>
          )}
        />
      </section>
    </Layout>
  );
}
