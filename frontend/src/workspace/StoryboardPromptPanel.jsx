import { Loader2, Sparkles } from "lucide-react";

function artifactTitle(artifact) {
  const created = artifact?.created_at ? new Date(artifact.created_at).toLocaleString() : "未知时间";
  const score = artifact?.payload?.prompt_report?.score;
  return `${created}${typeof score === "number" ? ` · Prompt ${score.toFixed(1)}` : ""}`;
}

function artifactFinalPrompt(artifact) {
  return artifact?.payload?.final_prompt || artifact?.payload?.compiled_prompt || "";
}

export function StoryboardPromptPanel({ selectedNode, artifacts = [], optimizingNodeId, optimizingVideoNodeId, onOptimize, onOptimizeVideo }) {
  if (!selectedNode) {
    return null;
  }
  const safeArtifacts = Array.isArray(artifacts) ? artifacts : [];
  const imageArtifacts = safeArtifacts.filter((artifact) => artifact.node_id === selectedNode.id && artifact.kind === "storyboard_image_prompt_version");
  const videoArtifacts = safeArtifacts.filter((artifact) => artifact.node_id === selectedNode.id && artifact.kind === "storyboard_video_prompt_version");
  const latest = imageArtifacts[0] || null;
  const latestVideo = videoArtifacts[0] || null;
  const panelBusy = Boolean(optimizingNodeId || optimizingVideoNodeId);
  const imageOptimizingThisNode = optimizingNodeId === selectedNode.id;
  const videoOptimizingThisNode = optimizingVideoNodeId === selectedNode.id;
  const canRunOptimize = typeof onOptimize === "function";
  const canRunVideoOptimize = typeof onOptimizeVideo === "function";
  const canOptimize = ["brief", "storyboard", "series_frame", "shot", "prompt_program", "semantic_spec", "selected_image"].includes(selectedNode.type);
  if (!canOptimize) {
    return null;
  }
  return (
    <section className="canvas-inspector-card">
      <div className="canvas-production-heading">
        <span>Storyboard Prompt</span>
      </div>
      <button className="primary-image-action compact" type="button" onClick={() => onOptimize?.(selectedNode)} disabled={panelBusy || !canRunOptimize}>
        {imageOptimizingThisNode ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
        <span>{latest ? "重新优化图像 Prompt" : "优化图像 Prompt"}</span>
      </button>
      <button className="secondary-image-action compact" type="button" onClick={() => onOptimizeVideo?.(selectedNode)} disabled={panelBusy || !canRunVideoOptimize}>
        {videoOptimizingThisNode ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
        <span>{latestVideo ? "重新优化视频 Prompt" : "优化视频 Prompt"}</span>
      </button>
      {latest ? (
        <div className="canvas-safe-fields">
          <div><span>最新版本</span><strong>{artifactTitle(latest)}</strong></div>
          <div><span>Final Prompt</span><strong>{artifactFinalPrompt(latest)}</strong></div>
        </div>
      ) : (
        <small>还没有保存的图像 Prompt 版本。优化后会把评分、Prompt Skill 输出和 trace 保存到当前节点。</small>
      )}
      {latestVideo ? (
        <div className="canvas-safe-fields">
          <div><span>最新视频版本</span><strong>{artifactTitle(latestVideo)}</strong></div>
          <div><span>Motion Prompt</span><strong>{artifactFinalPrompt(latestVideo)}</strong></div>
        </div>
      ) : (
        <small>还没有保存的视频 Prompt 版本。优化后会把运动提示词和图生视频上下文保存到当前节点。</small>
      )}
      {videoArtifacts.length > 1 ? <small>视频历史版本：{videoArtifacts.length} 个。</small> : null}
      {imageArtifacts.length > 1 ? <small>图像历史版本：{imageArtifacts.length} 个，可在后续阶段加入对比和回滚。</small> : null}
    </section>
  );
}
