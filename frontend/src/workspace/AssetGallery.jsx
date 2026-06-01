import { useMemo, useState } from "react";
import { Card, Empty, List, Segmented, Space, Tag, Typography } from "antd";
import { ImagePlus, Layers3, Video } from "lucide-react";

import { assetKindLabel, assetLabel, isImageAsset, isVideoAsset, safeDisplayUrl } from "./mediaUrls";

const ASSET_FILTERS = [
  { value: "all", label: "全部" },
  { value: "image", label: "图片" },
  { value: "video", label: "视频" },
];

function ReviewBadge({ status }) {
  const label = status === "approved" ? "已通过" : status === "rejected" ? "已拒绝" : "待审核";
  const color = status === "approved" ? "green" : status === "rejected" ? "red" : "gold";
  return <Tag color={color}>{label}</Tag>;
}

export function AssetGallery({ assets, tasks }) {
  const [filter, setFilter] = useState("all");
  const counts = useMemo(
    () => ({
      all: assets.length,
      image: assets.filter((asset) => isImageAsset(asset)).length,
      video: assets.filter((asset) => isVideoAsset(asset)).length,
    }),
    [assets],
  );
  const visibleAssets = useMemo(
    () => assets.filter((asset) => filter === "all" || (filter === "image" && isImageAsset(asset)) || (filter === "video" && isVideoAsset(asset))),
    [assets, filter],
  );

  const filterOptions = ASSET_FILTERS.map((item) => ({
    value: item.value,
    label: `${item.label} ${counts[item.value]}`,
  }));

  return (
    <section className="asset-gallery asset-library-workspace ant-asset-gallery">
      <Card
        className="app-light-card"
        title={
          <Space direction="vertical" size={2}>
            <Typography.Title level={4}>Media Library</Typography.Title>
            <Typography.Text type="secondary">图片和视频同属画布媒体资产，可进入 @引用、创作图谱和最终 JSON</Typography.Text>
          </Space>
        }
        extra={<Segmented value={filter} onChange={setFilter} options={filterOptions} aria-label="资产类型过滤" />}
      >
        <List
          grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
          dataSource={visibleAssets}
          locale={{
            emptyText: (
              <Empty description={assets.length ? "当前过滤条件下没有资产。" : "上传媒体或生成结果后，素材会自动进入项目资产库。"} />
            ),
          }}
          renderItem={(asset) => (
            <List.Item key={asset.id}>
              <Card className="asset-card media-asset-card app-light-card" cover={<AssetPreview asset={asset} />}>
                <Card.Meta
                  title={assetLabel(asset, assetKindLabel(asset))}
                  description={
                    <Space wrap size={[6, 6]}>
                      <Tag>{asset.media_type || "unknown media"}</Tag>
                      <ReviewBadge status={asset.review_status || "pending"} />
                    </Space>
                  }
                />
              </Card>
            </List.Item>
          )}
        />
      </Card>

      <Card
        className="app-light-card"
        title={
          <Space size={8} align="center">
            <Layers3 size={18} />
            <Typography.Title level={4}>Generation History</Typography.Title>
          </Space>
        }
        extra={<Tag>{tasks.length} 条记录</Tag>}
      >
        {tasks.length ? (
          <List
            className="compact-history-list"
            dataSource={tasks}
            renderItem={(task) => (
              <List.Item className={task.status === "failed" ? "task-failed" : ""} key={task.task_id}>
                <List.Item.Meta
                  title={`${task.kind} · ${task.status}`}
                  description={
                    <Space direction="vertical" size={4}>
                      <Typography.Text type="secondary">{task.error || task.input?.prompt || task.input?.input || "生成任务"}</Typography.Text>
                      {task.charged_credits !== undefined && task.charged_credits !== null ? <Tag>{task.charged_credits} 积分</Tag> : null}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty image={<Layers3 size={22} />} description="还没有生成任务；从图片工作区或画布提交后会在这里形成时间线。" />
        )}
      </Card>
    </section>
  );
}

function AssetPreview({ asset }) {
  const displayUrl = safeDisplayUrl(asset.url);
  const kindLabel = assetKindLabel(asset);
  const label = assetLabel(asset, kindLabel);
  const accessibleLabel = `项目${kindLabel}资产：${label}`;

  if (isImageAsset(asset) && displayUrl) {
    return <img className="asset-preview-media" src={displayUrl} alt={accessibleLabel} loading="lazy" decoding="async" referrerPolicy="no-referrer" />;
  }

  if (isVideoAsset(asset) && displayUrl) {
    return <video className="asset-preview-media" src={displayUrl} controls preload="metadata" playsInline aria-label={accessibleLabel} />;
  }

  return (
    <div className="asset-placeholder asset-preview-media" role="img" aria-label={accessibleLabel}>
      {isVideoAsset(asset) ? <Video size={30} /> : <ImagePlus size={30} />}
      <span>{kindLabel}资产</span>
    </div>
  );
}
