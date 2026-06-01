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
          const label = ACTION_LABELS[item.action_type] || item.action_type;
          const quota = quotas.get(item.action_type);
          const text = `${label}: ${item.cost} 点${quota ? ` · ${quota.used_count}/${quota.limit_count}` : ""}`;
          return (
            <Tooltip title={text} key={item.action_type}>
              <Tag>{text}</Tag>
            </Tooltip>
          );
        })}
    </Space>
  );
}
