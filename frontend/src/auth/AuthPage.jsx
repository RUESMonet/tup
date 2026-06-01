import { useState } from "react";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LogIn } from "lucide-react";

import { loginAccount, registerAccount } from "../api/auth";

export function AuthPage({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ username: "", email: "", password: "" });
  const [status, setStatus] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setStatus("");
    try {
      const payload = mode === "register" ? await registerAccount(form) : await loginAccount({ username: form.username, password: form.password });
      onAuthenticated(payload.user);
    } catch (error) {
      setStatus(error?.message || "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

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
            <Input.Password value={form.password} onChange={(event) => updateField("password", event.target.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} />
          </Form.Item>
          {status ? <Alert type="error" message={status} showIcon role="alert" /> : null}
          <Button type="primary" block htmlType="submit" loading={submitting} disabled={submitting || !form.username.trim() || !form.password.trim() || (mode === "register" && !form.email.trim())}>
            {submitting ? "处理中" : mode === "register" ? "注册并进入" : "登录"}
          </Button>
          <Button type="link" block onClick={() => setMode(mode === "register" ? "login" : "register")}>
            {mode === "register" ? "已有账号？去登录" : "没有账号？创建一个"}
          </Button>
        </Form>
      </Card>
    </main>
  );
}
