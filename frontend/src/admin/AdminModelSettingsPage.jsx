import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Form, Input, Layout, Select, Space, Spin, Typography } from "antd";
import { ArrowLeft, Save, ShieldCheck } from "lucide-react";

import { fetchModelSettings, updateModelSettings } from "../api/admin";

const FIELD_GROUPS = [
  {
    title: "共享 OpenAI",
    fields: ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
  },
  {
    title: "图片生成",
    fields: ["OPENAI_IMAGE_API_KEY", "OPENAI_IMAGE_BASE_URL", "OPENAI_IMAGE_MODEL", "USE_MOCK_IMAGES"],
  },
  {
    title: "视觉评估",
    fields: ["OPENAI_EVALUATOR_API_KEY", "OPENAI_EVALUATOR_BASE_URL", "OPENAI_EVALUATOR_MODEL"],
  },
  {
    title: "提示词草稿",
    fields: ["OPENAI_PROMPT_DRAFT_BASE_URL", "OPENAI_PROMPT_DRAFT_MODEL"],
  },
  {
    title: "提示词优化",
    fields: ["OPENAI_PROMPT_OPTIMIZER_BASE_URL", "OPENAI_PROMPT_OPTIMIZER_MODEL"],
  },
  {
    title: "视频生成",
    fields: ["VIDEO_API_KEY", "VIDEO_BASE_URL", "VIDEO_MODEL", "VIDEO_GENERATE_ENDPOINT", "USE_MOCK_VIDEOS"],
  },
  {
    title: "运行参数",
    fields: ["REQUEST_TIMEOUT_SECONDS", "MODEL_REQUEST_RETRIES"],
  },
];

const FIELD_LABELS = {
  OPENAI_API_KEY: "通用 API Key",
  OPENAI_BASE_URL: "通用 Base URL",
  OPENAI_IMAGE_API_KEY: "图片 API Key",
  OPENAI_IMAGE_BASE_URL: "图片 Base URL",
  OPENAI_IMAGE_MODEL: "图片模型",
  OPENAI_EVALUATOR_API_KEY: "评估 API Key",
  OPENAI_EVALUATOR_BASE_URL: "评估 Base URL",
  OPENAI_EVALUATOR_MODEL: "评估模型",
  OPENAI_PROMPT_DRAFT_BASE_URL: "提示词 Base URL",
  OPENAI_PROMPT_DRAFT_MODEL: "提示词模型",
  OPENAI_PROMPT_OPTIMIZER_BASE_URL: "提示词优化 Base URL",
  OPENAI_PROMPT_OPTIMIZER_MODEL: "提示词优化模型",
  USE_MOCK_IMAGES: "图片 Mock 模式",
  VIDEO_API_KEY: "视频 API Key",
  VIDEO_BASE_URL: "视频 Base URL",
  VIDEO_MODEL: "视频模型",
  VIDEO_GENERATE_ENDPOINT: "视频接口路径",
  USE_MOCK_VIDEOS: "视频 Mock 模式",
  REQUEST_TIMEOUT_SECONDS: "请求超时秒数",
  MODEL_REQUEST_RETRIES: "请求重试次数",
};

const BOOLEAN_FIELDS = new Set(["USE_MOCK_IMAGES", "USE_MOCK_VIDEOS"]);

export function AdminModelSettingsPage({ onBack }) {
  const [settings, setSettings] = useState({});
  const [drafts, setDrafts] = useState({});
  const [cleared, setCleared] = useState({});
  const [touched, setTouched] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");
  const [statusKind, setStatusKind] = useState("success");

  useEffect(() => {
    loadSettings();
  }, []);

  const flatFields = useMemo(() => FIELD_GROUPS.flatMap((group) => group.fields), []);

  async function loadSettings() {
    try {
      const payload = await fetchModelSettings();
      setSettings(payload.settings || {});
      setDrafts(buildDrafts(payload.settings || {}));
      setCleared({});
      setTouched({});
      setStatus("");
      setStatusKind("success");
    } catch (error) {
      setStatusKind("error");
      setStatus(error?.message || "模型配置加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function saveSettings() {
    const payload = {};
    for (const key of flatFields) {
      const entry = settings[key] || {};
      if (entry.secret) {
        if (cleared[key]) {
          payload[key] = null;
        }
        continue;
      }
      if (cleared[key]) {
        payload[key] = null;
        continue;
      }
      const current = stringifyValue(entry.value);
      const draft = stringifyValue(drafts[key]);
      if (draft !== current || (touched[key] && entry.source !== "database")) {
        payload[key] = BOOLEAN_FIELDS.has(key) ? draft === "true" : draft;
      }
    }
    setSaving(true);
    try {
      const response = await updateModelSettings({ settings: payload });
      setSettings(response.settings || {});
      setDrafts(buildDrafts(response.settings || {}));
      setCleared({});
      setTouched({});
      setStatusKind("success");
      setStatus("模型配置已保存");
    } catch (error) {
      setStatusKind("error");
      setStatus(error?.message || "模型配置保存失败");
    } finally {
      setSaving(false);
    }
  }

  function updateDraft(key, value) {
    setDrafts((current) => ({ ...current, [key]: value }));
    setCleared((current) => ({ ...current, [key]: false }));
    setTouched((current) => ({ ...current, [key]: true }));
  }

  function clearOverride(key) {
    setCleared((current) => ({ ...current, [key]: true }));
    setDrafts((current) => ({ ...current, [key]: settings[key]?.secret ? "" : stringifyValue(settings[key]?.value) }));
    setTouched((current) => ({ ...current, [key]: false }));
  }

  return (
    <Layout className="project-shell admin-settings-shell app-light-shell">
      <section className="project-page-shell">
        <Card className="project-topbar app-light-card">
          <div>
            <Typography.Title level={1}>模型配置</Typography.Title>
            <Typography.Text type="secondary">管理员可在这里配置 OpenAI 兼容图片、评估、提示词和视频模型</Typography.Text>
          </div>
          <Space wrap className="project-actions">
            <Button type="default" icon={<ArrowLeft size={17} />} onClick={onBack}>返回项目</Button>
            <Button type="primary" icon={<Save size={17} />} onClick={saveSettings} disabled={loading} loading={saving}>保存配置</Button>
          </Space>
        </Card>
        {status ? <Alert type={statusKind === "error" ? "error" : "success"} message={status} showIcon role="status" /> : null}
        <Alert
          type="info"
          showIcon
          message="密钥只能通过 .env 或环境变量配置"
          description="API Key 字段为只读展示，页面仅显示已配置密钥的掩码状态，不会提交或显示真实密钥值。"
        />
        {loading ? (
          <Card className="auth-card app-light-card">
            <Spin tip="正在加载模型配置">
              <div className="admin-loading-placeholder" aria-hidden="true" />
            </Spin>
          </Card>
        ) : null}
        {!loading ? (
          <section className="admin-settings-grid ant-admin-settings-grid">
            {FIELD_GROUPS.map((group) => (
              <Card className="admin-settings-card app-light-card" key={group.title} title={group.title}>
                <Typography.Text type="secondary">数据库覆盖值优先，清除后回退环境变量或默认值</Typography.Text>
                <Form layout="vertical" requiredMark={false}>
                  {group.fields.map((key) => renderField(key, settings[key], drafts[key], Boolean(cleared[key]), updateDraft, clearOverride))}
                </Form>
              </Card>
            ))}
          </section>
        ) : null}
      </section>
    </Layout>
  );
}

function renderField(key, entry = {}, draft = "", isCleared, onChange, onClear) {
  const fieldId = `admin-field-${key}`;
  const isSecret = Boolean(entry.secret);
  const label = (
    <span className="admin-field-heading">
      <span>{FIELD_LABELS[key] || key}</span>
      <small><ShieldCheck size={13} />{entry.source || "unset"}</small>
    </span>
  );

  return (
    <Form.Item className={`admin-field ${isCleared ? "cleared" : ""}`} key={key} label={label} extra={fieldMeta(entry, isCleared)} htmlFor={fieldId}>
      <Space.Compact block>
        {isSecret ? <SecretInput id={fieldId} entry={entry} /> : <ValueInput id={fieldId} fieldKey={key} value={draft} onChange={onChange} />}
        <Button type="default" onClick={() => onClear(key)} disabled={isSecret && entry.source !== "database"}>
          {isSecret ? "清除密钥覆盖" : "使用环境默认"}
        </Button>
      </Space.Compact>
    </Form.Item>
  );
}

function SecretInput({ id, entry }) {
  const displayValue = entry.configured ? entry.masked_value || "已隐藏" : "";
  const placeholder = entry.configured ? "已通过 .env / 环境变量配置" : "未配置，请在 .env / 环境变量中设置";
  return (
    <Input.Password
      id={id}
      value={displayValue}
      placeholder={placeholder}
      autoComplete="off"
      readOnly
      disabled
    />
  );
}

function ValueInput({ id, fieldKey, value, onChange }) {
  if (BOOLEAN_FIELDS.has(fieldKey)) {
    return (
      <Select
        id={id}
        value={stringifyValue(value)}
        onChange={(selectedValue) => onChange(fieldKey, selectedValue)}
        options={[
          { value: "true", label: "开启" },
          { value: "false", label: "关闭" },
        ]}
      />
    );
  }
  return <Input id={id} value={stringifyValue(value)} onChange={(event) => onChange(fieldKey, event.target.value)} />;
}

function buildDrafts(settings) {
  return Object.fromEntries(
    Object.entries(settings).map(([key, entry]) => [key, entry.secret ? "" : stringifyValue(entry.value)]),
  );
}

function stringifyValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function fieldMeta(entry = {}, isCleared) {
  if (isCleared) {
    return "保存后清除数据库覆盖值";
  }
  if (entry.secret) {
    return entry.configured ? `密钥已配置：${entry.masked_value || "已隐藏"}` : "密钥未配置";
  }
  return entry.configured ? "当前有效值" : "当前未配置";
}
