import { useState } from "react";
import { Clapperboard, Loader2, Video } from "lucide-react";

import { createProjectVideoTask } from "../api/generation";
import { assetLabel, safeDisplayUrl } from "./mediaUrls";
import { useProjectGenerationTask } from "./useProjectGenerationTask";

export function VideoWorkspace({ projectId, assets, onStatus, onComplete }) {
  const [prompt, setPrompt] = useState("香水瓶在柔和雾气中缓慢旋转，镜头推进，电影质感");
  const [sourceImageAssetId, setSourceImageAssetId] = useState("");
  const [duration, setDuration] = useState(4);
  const generation = useProjectGenerationTask({
    createTask: (payload) => createProjectVideoTask(projectId, payload),
    onStatus,
    onComplete,
  });
  const result = generation.task?.result;
  const busy = generation.running || generation.submitting;
  const promptLength = prompt.trim().length;

  function submit() {
    generation.submit(
      {
        prompt: prompt.trim(),
        source_image_asset_id: sourceImageAssetId || null,
        duration: Number(duration) || 4,
      },
      "视频",
    );
  }

  return (
    <section className="workspace-grid">
      <div className="image-editor-panel">
        <div className="panel-heading">
          <div>
            <strong>视频生成</strong>
            <span>输入提示词，可选项目图片作为首帧参考</span>
          </div>
          <button className="primary-image-action compact" type="button" onClick={submit} disabled={!prompt.trim() || busy}>
            {busy ? <Loader2 className="spinning" size={18} /> : <Clapperboard size={18} />}
            <span>{busy ? "生成中" : "生成视频"}</span>
          </button>
        </div>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} spellCheck={false} aria-label="项目视频生成提示词" />
        <div className="prompt-meta">
          <span>{promptLength ? `已输入 ${promptLength} 个字符` : "输入视频提示词后可生成项目视频"}</span>
          <span>视频结果会自动保存为资产。</span>
        </div>
        <div className="image-controls">
          <label>
            <span>源图片资产</span>
            <select value={sourceImageAssetId} onChange={(event) => setSourceImageAssetId(event.target.value)} disabled={busy}>
              <option value="">不使用源图片</option>
              {assets
                .filter((asset) => asset.kind === "image")
                .map((asset, index) => (
                  <option key={asset.id} value={asset.id}>
                    图片 {index + 1} · {assetLabel(asset, "图片")}
                  </option>
                ))}
            </select>
            <small className="field-help">可选项目内图片作为首帧参考。</small>
          </label>
          <label>
            <span>时长秒</span>
            <input type="number" min="1" max="60" value={duration} onChange={(event) => setDuration(event.target.value)} disabled={busy} />
            <small className="field-help">建议先用短视频验证运动效果。</small>
          </label>
        </div>
      </div>
      <div className="image-result-panel">
        <div className="result-frame video-frame">
          {result?.url ? (
            result.url.startsWith("mock://") || !safeDisplayUrl(result.url) ? (
              <div className="result-empty">
                <Video size={38} />
                <span>{result.url.startsWith("mock://") ? `Mock 视频已生成：${result.url}` : "视频已生成，请在资产列表查看"}</span>
              </div>
            ) : (
              <video src={safeDisplayUrl(result.url)} controls referrerPolicy="no-referrer" />
            )
          ) : (
            <div className="result-empty">
              {busy ? <Loader2 className="spinning" size={34} /> : <Video size={38} />}
              <span>{busy ? "正在等待视频结果" : "项目视频结果会显示在这里"}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
