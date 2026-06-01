import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ImagePlus, Loader2, Sparkles, UploadCloud, WandSparkles, X } from "lucide-react";

import { createProjectImageEditTask, createProjectImageTask } from "../api/generation";
import { uploadProjectAsset } from "../api/projects";
import { Metric } from "../image-optimizer/components/Metric";
import { optimizePromptSkill } from "../image-optimizer/api";
import { defaultPrompt } from "../image-optimizer/constants";
import { useImageModels } from "../image-optimizer/hooks/useImageModels";
import { usePromptAnalysis } from "../image-optimizer/hooks/usePromptAnalysis";
import { promptForRequest, promptJsonText, readablePromptText } from "../image-optimizer/promptFormatting";
import { normalizeNumber } from "../image-optimizer/taskUtils";
import { assetLabel, isImageAsset, safeDisplayUrl } from "./mediaUrls";
import { PromptOptimizationTrace } from "./PromptOptimizationTrace";
import { useProjectGenerationTask } from "./useProjectGenerationTask";

const ACTION_OPTIONS = [
  { value: "text_to_image", label: "文生图", help: "不使用参考图，适合从零生成。" },
  { value: "image_to_image", label: "参考图生成", help: "锁定参考图的主体、材质、构图或风格线索。" },
  { value: "edit", label: "图片编辑", help: "基于项目图片修改背景、姿态、元素或局部语义。" },
  { value: "inpaint", label: "蒙版修复", help: "使用选中的 mask 资产限制可编辑区域。" },
  { value: "style_transfer", label: "风格迁移", help: "保留主体身份，迁移参考图风格。" },
];

export function ImageWorkspace({ projectId, assets = [], onStatus, onComplete }) {
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [activePromptPayload, setActivePromptPayload] = useState(null);
  const [threshold, setThreshold] = useState(8);
  const [maxIter, setMaxIter] = useState(3);
  const [actionType, setActionType] = useState("text_to_image");
  const [selectedAssetIds, setSelectedAssetIds] = useState([]);
  const [maskAssetId, setMaskAssetId] = useState("");
  const [promptSkill, setPromptSkill] = useState(null);
  const [optimizingSkill, setOptimizingSkill] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadRef = useRef(null);
  const { models, model, setModel, loadModels } = useImageModels({ onStatus });
  const { analysis, streamedText, analyzing, analyzePrompt, clearAnalysis } = usePromptAnalysis({ prompt, activePromptPayload, onStatus, streamDraft: true });
  const generation = useProjectGenerationTask({
    createTask: (payload) => (payload.kind === "image_edit" ? createProjectImageEditTask(projectId, payload.body) : createProjectImageTask(projectId, payload.body)),
    onStatus,
    onComplete,
  });
  const imageAssets = useMemo(() => assets.filter((asset) => isImageAsset(asset)), [assets]);
  const selectedAssets = useMemo(() => imageAssets.filter((asset) => selectedAssetIds.includes(asset.id)), [imageAssets, selectedAssetIds]);
  const selectedMask = useMemo(() => imageAssets.find((asset) => asset.id === maskAssetId) || null, [imageAssets, maskAssetId]);
  const sourceAssetIds = useMemo(() => (actionType === "inpaint" ? selectedAssetIds.filter((assetId) => assetId !== maskAssetId) : selectedAssetIds), [actionType, maskAssetId, selectedAssetIds]);
  const sourceAssets = useMemo(() => imageAssets.filter((asset) => sourceAssetIds.includes(asset.id)), [imageAssets, sourceAssetIds]);
  const requiresSource = actionType !== "text_to_image";
  const result = generation.task?.result;
  const imageSrc = result?.image_b64_json ? safeDisplayUrl(`data:${result.image_media_type || "image/png"};base64,${result.image_b64_json}`) : safeDisplayUrl(result?.image_url || "");
  const busy = generation.running || generation.submitting || uploading || optimizingSkill;
  const error = generation.task?.error;
  const promptLength = prompt.trim().length;
  const optimizedPromptPayload = useMemo(
    () => analysis?.optimized_prompt || analysis?.candidate_prompts?.[0]?.optimized_prompt || null,
    [analysis],
  );
  const optimizedPromptText = useMemo(() => streamedText || (optimizedPromptPayload ? promptJsonText(optimizedPromptPayload) : ""), [optimizedPromptPayload, streamedText]);
  const promptSkillText = promptSkill?.final_english_prompt || "";
  const draftPromptSpec = promptSkill?.optimized_prompt?.prompt_spec || null;
  const resultPromptSpec = result?.prompt_skill?.optimized_prompt?.prompt_spec || result?.prompt_skill?.prompt_spec || null;
  const activeAction = ACTION_OPTIONS.find((item) => item.value === actionType) || ACTION_OPTIONS[0];
  const studioStages = [
    { title: "Create", label: "创意简报", value: prompt.trim() ? "Brief ready" : "等待输入", active: Boolean(prompt.trim()) },
    { title: "Refine", label: "案例编译", value: draftPromptSpec ? "Spec compiled" : promptSkill ? "Skill ready" : "未编译", active: Boolean(draftPromptSpec || promptSkill) },
    { title: "Compose", label: "资产成片", value: selectedAssets.length ? `${selectedAssets.length} refs` : result ? "Result ready" : "资产待选", active: Boolean(selectedAssets.length || result) },
  ];

  useEffect(() => {
    loadModels();
  }, []);

  function resetDraftOptimization() {
    setActivePromptPayload(null);
    setPromptSkill(null);
    clearAnalysis();
  }

  function handlePromptChange(event) {
    setPrompt(event.target.value);
    resetDraftOptimization();
  }

  function handleActionTypeChange(event) {
    setActionType(event.target.value);
    resetDraftOptimization();
  }

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || uploading) {
      return;
    }
    setUploading(true);
    onStatus({ kind: "loading", message: "正在上传项目媒体" });
    try {
      const asset = await uploadProjectAsset(projectId, file);
      resetDraftOptimization();
      if (isImageAsset(asset)) {
        setSelectedAssetIds((current) => [...new Set([...current, asset.id])]);
      }
      await onComplete?.(asset);
      onStatus({ kind: "ready", message: isImageAsset(asset) ? "参考图已上传并选中" : "视频已上传，可在画布中作为媒体引用" });
    } catch (error) {
      onStatus({ kind: "failed", message: error?.message || "项目媒体上传失败" });
    } finally {
      setUploading(false);
    }
  }

  function toggleAsset(assetId) {
    resetDraftOptimization();
    setSelectedAssetIds((current) => (current.includes(assetId) ? current.filter((item) => item !== assetId) : [...current, assetId]));
    if (maskAssetId === assetId) {
      setMaskAssetId("");
    }
  }

  function handleMaskAssetChange(event) {
    setMaskAssetId(event.target.value);
    resetDraftOptimization();
  }

  async function optimizeWithPromptSkill() {
    if (!prompt.trim() || optimizingSkill || (requiresSource && !sourceAssets.length) || (actionType === "inpaint" && !selectedMask)) {
      return;
    }
    setOptimizingSkill(true);
    setPromptSkill(null);
    onStatus({ kind: "loading", message: "正在运行工业级 Prompt Skill 优化" });
    try {
      const response = await optimizePromptSkill({
        prompt: promptForRequest(prompt, activePromptPayload),
        action_type: actionType,
        source_images: requiresSource ? sourceAssets.map(assetToImageSource) : [],
        mask_image: actionType === "inpaint" && selectedMask ? assetToImageSource(selectedMask, "mask") : null,
        params: {},
        defects: [],
      });
      setPromptSkill(response);
      onStatus({ kind: "ready", message: "Prompt Skill 优化完成，可套用或直接生成" });
    } catch (error) {
      onStatus({ kind: "failed", message: error?.message || "Prompt Skill 优化失败" });
    } finally {
      setOptimizingSkill(false);
    }
  }

  function submitGeneration(promptText, promptPayload) {
    const requestPrompt = promptForRequest(promptText, promptPayload);
    if (requiresSource) {
      generation.submit(
        {
          kind: "image_edit",
          body: {
            prompt: requestPrompt,
            model,
            source_image_asset_ids: sourceAssetIds,
            mask_asset_id: actionType === "inpaint" ? maskAssetId || null : null,
            action_type: actionType,
            threshold: normalizeNumber(threshold, 8),
            max_iter: normalizeNumber(maxIter, 3),
            params: {},
          },
        },
        "图片编辑",
      );
      return;
    }
    generation.submit(
      {
        kind: "image",
        body: {
          input: requestPrompt,
          model,
          threshold: normalizeNumber(threshold, 8),
          max_iter: normalizeNumber(maxIter, 3),
          skip_prompt_evaluation: false,
        },
      },
      "图片",
    );
  }

  function submit() {
    if (!canSubmit(prompt, busy, requiresSource, sourceAssetIds, actionType, maskAssetId)) {
      return;
    }
    submitGeneration(prompt, activePromptPayload);
  }

  function useOptimizedPrompt() {
    if (!optimizedPromptPayload || !optimizedPromptText || !canSubmit(prompt, busy, requiresSource, sourceAssetIds, actionType, maskAssetId)) {
      return;
    }
    setPrompt(optimizedPromptText);
    setActivePromptPayload(optimizedPromptPayload);
    submitGeneration(optimizedPromptText, optimizedPromptPayload);
  }

  function applyPromptSkillPrompt() {
    if (!promptSkillText) {
      return;
    }
    setPrompt(promptSkillText);
    setActivePromptPayload(null);
    clearAnalysis();
  }

  function generatePromptSkillPrompt() {
    if (!promptSkillText || !canSubmit(promptSkillText, busy, requiresSource, sourceAssetIds, actionType, maskAssetId)) {
      return;
    }
    submitGeneration(promptSkillText, null);
  }

  return (
    <section className="studio-workspace-shell image-studio-shell">
      <div className="studio-flow-header compact" aria-label="专业创作流程">
        {studioStages.map((stage) => (
          <div className={stage.active ? "studio-flow-step active" : "studio-flow-step"} key={stage.title}>
            <span>{stage.title}</span>
            <strong>{stage.label}</strong>
            <small>{stage.value}</small>
          </div>
        ))}
      </div>

      <div className="image-studio-layout">
        <div className="image-studio-column image-studio-compose">
          <section className="image-editor-panel studio-panel image-brief-panel">
            <div className="panel-heading">
              <div>
                <strong>创意简报</strong>
                <span>先定义主体、场景、镜头、光线、材质和限制条件</span>
              </div>
              <button className="primary-image-action compact" type="button" onClick={analyzePrompt} disabled={!prompt.trim() || busy || analyzing}>
                {analyzing ? <Loader2 className="spinning" size={18} /> : <WandSparkles size={18} />}
                <span>{analyzing ? "优化中" : "优化提示词"}</span>
              </button>
            </div>
            <textarea value={prompt} onChange={handlePromptChange} spellCheck={false} aria-label="项目图片生成提示词" />
            <div className="prompt-meta">
              <span>{promptLength ? `已输入 ${promptLength} 个字符` : "输入提示词后可生成项目图片"}</span>
              <span>{activeAction.help}</span>
            </div>
          </section>

          <section className="studio-panel image-generation-panel">
            <div className="section-kicker">
              <strong>生成设置</strong>
              <span>{requiresSource ? "参考图工作流" : "文生图工作流"}</span>
            </div>
            <div className="image-controls">
              <label>
                <span>模型</span>
                <select value={model} onChange={(event) => setModel(event.target.value)} disabled={busy}>
                  {models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id} {item.configured ? "" : "(未配置)"}
                    </option>
                  ))}
                </select>
                <small className="field-help">当前项目图片任务使用的模型。</small>
              </label>
              <label>
                <span>目标评分</span>
                <input type="number" min="0" max="10" step="0.5" value={threshold} onChange={(event) => setThreshold(event.target.value)} disabled={busy} />
                <small className="field-help">达到目标评分后停止迭代。</small>
              </label>
              <label>
                <span>迭代次数</span>
                <input type="number" min="1" max="10" value={maxIter} onChange={(event) => setMaxIter(event.target.value)} disabled={busy} />
                <small className="field-help">限制最多优化轮数。</small>
              </label>
            </div>
            <div className="image-action-row">
              <button className="primary-image-action" type="button" onClick={submit} disabled={!canSubmit(prompt, busy, requiresSource, sourceAssetIds, actionType, maskAssetId) || analyzing}>
                {generation.running || generation.submitting ? <Loader2 className="spinning" size={18} /> : <Sparkles size={18} />}
                <span>{requiresSource ? "提交图片编辑" : "生成项目图片"}</span>
              </button>
            </div>
          </section>
        </div>

        <div className="image-studio-column image-studio-intelligence">
          <section className="prompt-skill-workspace studio-panel image-reference-panel">
            <div className="section-kicker">
              <strong>参考资产</strong>
              <span>{selectedAssets.length ? `已选 ${selectedAssets.length} 张参考图` : "选择图片资产或上传媒体"}</span>
            </div>
            <div className="image-controls prompt-skill-controls">
              <label>
                <span>任务类型</span>
                <select value={actionType} onChange={handleActionTypeChange} disabled={busy}>
                  {ACTION_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
                <small className="field-help">用于 Prompt Skill 意图识别和编辑策略。</small>
              </label>
              <label>
                <span>蒙版资产</span>
                <select value={maskAssetId} onChange={handleMaskAssetChange} disabled={busy || actionType !== "inpaint"}>
                  <option value="">不使用蒙版</option>
                  {imageAssets.map((asset) => (
                    <option key={asset.id} value={asset.id}>{assetLabel(asset, "蒙版")}</option>
                  ))}
                </select>
                <small className="field-help">仅蒙版修复模式需要。</small>
              </label>
            </div>
            <div className="asset-picker-actions">
              <input ref={uploadRef} type="file" accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime,.mov" onChange={handleUpload} hidden />
              <button className="secondary-image-action" type="button" onClick={() => uploadRef.current?.click()} disabled={uploading || busy}>
                {uploading ? <Loader2 className="spinning" size={17} /> : <UploadCloud size={17} />}
                <span>{uploading ? "上传中" : "上传媒体"}</span>
              </button>
              <button className="secondary-image-action" type="button" onClick={optimizeWithPromptSkill} disabled={!prompt.trim() || busy || (requiresSource && !sourceAssets.length) || (actionType === "inpaint" && !selectedMask)}>
                {optimizingSkill ? <Loader2 className="spinning" size={17} /> : <WandSparkles size={17} />}
                <span>工业 Prompt Skill 优化</span>
              </button>
            </div>
            <small className="field-help">视频会进入项目资产与画布媒体引用；当前图片生成参考选择器只显示图片。</small>
            <div className="asset-picker-grid compact">
              {imageAssets.map((asset) => {
                const selected = selectedAssetIds.includes(asset.id);
                return (
                  <button type="button" className={selected ? "asset-picker-card selected" : "asset-picker-card"} key={asset.id} onClick={() => toggleAsset(asset.id)} disabled={busy} aria-pressed={selected}>
                    {safeDisplayUrl(asset.url) ? <img src={safeDisplayUrl(asset.url)} alt="项目参考图" loading="lazy" decoding="async" referrerPolicy="no-referrer" /> : <ImagePlus size={24} />}
                    <span>{assetLabel(asset, "图片")}</span>
                    {selected ? <X size={15} /> : null}
                  </button>
                );
              })}
              {!imageAssets.length ? <div className="reference-empty">还没有项目图片资产，先上传参考图或生成一张图片。</div> : null}
            </div>
          </section>

          <section className="studio-panel prompt-intelligence-panel">
            <div className="section-kicker">
              <strong>Prompt Intelligence</strong>
              <span>优化提示词、Prompt Skill 与结构化蓝图</span>
            </div>
            {analyzing ? (
              <div className="optimized-prompt-preview loading">
                <Loader2 className="spinning" size={18} />
                <span>正在生成优化后的提示词…</span>
              </div>
            ) : null}
            {optimizedPromptPayload && optimizedPromptText ? (
              <div className="optimized-prompt-preview">
                <div className="section-kicker">
                  <strong>优化后的提示词</strong>
                  <span>确认后使用该提示词生成项目图片</span>
                </div>
                <pre>{optimizedPromptText}</pre>
                <div className="optimized-prompt-actions">
                  <button className="primary-image-action" type="button" onClick={useOptimizedPrompt} disabled={!canSubmit(prompt, busy, requiresSource, sourceAssetIds, actionType, maskAssetId) || analyzing}>
                    {busy ? <Loader2 className="spinning" size={18} /> : <Sparkles size={18} />}
                    <span>{busy ? "生成中" : "使用此提示词生成"}</span>
                  </button>
                  <button className="secondary-image-action" type="button" onClick={submit} disabled={!canSubmit(prompt, busy, requiresSource, sourceAssetIds, actionType, maskAssetId) || analyzing}>
                    直接生成原提示词
                  </button>
                </div>
              </div>
            ) : null}
            {promptSkill ? <PromptSkillPreview response={promptSkill} onApply={applyPromptSkillPrompt} onGenerate={generatePromptSkillPrompt} disabled={busy} /> : null}
            <PromptSpecStudio spec={draftPromptSpec} promptSkill={promptSkill} />
          </section>
        </div>

        <aside className="image-result-panel image-studio-output">
          <div className={`result-frame${error ? " failed" : ""}`}>
            {imageSrc ? (
              <img src={imageSrc} alt="生成结果" decoding="async" referrerPolicy="no-referrer" />
            ) : (
              <div className={`result-empty${error ? " failed" : ""}`}>
                {error ? <AlertCircle size={34} /> : generation.running ? <Loader2 className="spinning" size={34} /> : <ImagePlus size={38} />}
                <span>{error ? "生成失败，请查看错误信息" : generation.running ? "正在等待图片结果" : "项目图片结果会显示在这里"}</span>
              </div>
            )}
          </div>
          {error ? <div className="result-error">{error}</div> : null}
          <dl className="result-stats">
            <Metric label="状态" value={generation.task?.status || "idle"} />
            <Metric label="评分" value={result?.score == null ? "-" : Number(result.score).toFixed(1)} />
            <Metric label="迭代" value={result?.iterations || "-"} />
          </dl>
          <PromptOptimizationTrace trace={result?.optimization_trace} />
          {result?.prompt_skill ? <PromptSkillSummary promptSkill={result.prompt_skill} /> : null}
          <PromptSpecStudio spec={resultPromptSpec} promptSkill={result?.prompt_skill} compact />
          {result?.final_prompt ? (
            <div className="final-prompt">
              <strong>最终提示词</strong>
              <pre>{readablePromptText(result.final_prompt)}</pre>
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function PromptSkillPreview({ response, onApply, onGenerate, disabled }) {
  return (
    <div className="optimized-prompt-preview prompt-skill-preview">
      <div className="section-kicker">
        <strong>Prompt Skill 优化结果</strong>
        <span>{response.intent?.action_type} · {response.intent?.profile}</span>
      </div>
      <pre>{response.final_english_prompt}</pre>
      <PromptSkillSummary promptSkill={response} />
      <div className="optimized-prompt-actions">
        <button className="secondary-image-action" type="button" onClick={onApply} disabled={disabled}>套用到编辑框</button>
        <button className="primary-image-action" type="button" onClick={onGenerate} disabled={disabled}>使用 Prompt Skill 生成</button>
      </div>
    </div>
  );
}

function PromptSpecStudio({ spec, promptSkill, compact = false }) {
  if (!spec) {
    return promptSkill ? (
      <div className="prompt-spec-studio empty">
        <strong>Prompt Spec 编译器</strong>
        <span>已完成 Skill 优化，等待后端返回结构化 Prompt Spec。</span>
      </div>
    ) : null;
  }
  const cases = spec.case_strategy?.selected_cases || [];
  const principles = spec.case_strategy?.visual_principles || [];
  const sections = compact ? [] : spec.final_prompt_sections || [];
  return (
    <div className={compact ? "prompt-spec-studio compact" : "prompt-spec-studio"}>
      <div className="section-kicker">
        <strong>Prompt Spec 创作蓝图</strong>
        <span>{spec.generation_plan?.compiler || "case-aware compiler"}</span>
      </div>
      <div className="prompt-spec-grid">
        <SpecBlock title="创意方向" value={spec.creative_direction?.core_brief} meta={spec.creative_direction?.target_profile} />
        <SpecBlock title="构图" value={spec.composition?.layout} meta={spec.composition?.camera} />
        <SpecBlock title="光影材质" value={spec.style_system?.lighting} meta={(spec.style_system?.materials || []).slice(0, 2).join(" / ")} />
        <SpecBlock title="质量约束" value={(spec.constraints?.quality_gates || []).join(" / ")} meta={(spec.constraints?.avoid || []).slice(0, 2).join(" / ")} />
      </div>
      {cases.length ? (
        <div className="case-dna-strip" aria-label="案例 DNA">
          {cases.slice(0, compact ? 2 : 4).map((item) => (
            <span key={item.case_id || item.title}>{item.title || item.case_id}</span>
          ))}
        </div>
      ) : null}
      {!compact && principles.length ? <ul className="spec-principles">{principles.slice(0, 5).map((item) => <li key={item}>{item}</li>)}</ul> : null}
      {!compact && sections.length ? <pre>{sections.join("\n")}</pre> : null}
    </div>
  );
}

function SpecBlock({ title, value, meta }) {
  return (
    <div className="spec-block">
      <span>{title}</span>
      <strong>{value || "等待编译"}</strong>
      {meta ? <small>{meta}</small> : null}
    </div>
  );
}

function PromptSkillSummary({ promptSkill }) {
  const gates = promptSkill?.quality_gates || [];
  const anchors = promptSkill?.character_policy?.anchors || [];
  const cases = promptSkill?.reference_usage?.matched_cases || [];
  return (
    <div className="prompt-skill-summary">
      <div className="prompt-chip-list">
        {(promptSkill?.edit_policy?.preserve || []).slice(0, 3).map((item) => <span className="prompt-chip" key={item}>{item}</span>)}
        {anchors.slice(0, 6).map((item) => <span className="prompt-chip" key={item}>{item}</span>)}
      </div>
      {gates.length ? <ul>{gates.slice(0, 4).map((gate) => <li key={gate}>{gate}</li>)}</ul> : null}
      {cases.length ? <small>参考案例：{cases.slice(0, 3).map((item) => item.title || item.id).join(" / ")}</small> : null}
    </div>
  );
}

function assetToImageSource(asset, role = "source") {
  return {
    asset_id: asset.id,
    media_type: asset.media_type,
    role,
    metadata: { project_id: asset.project_id, filename: asset.metadata?.filename },
  };
}

function canSubmit(prompt, busy, requiresSource, sourceAssetIds, actionType, maskAssetId) {
  if (!prompt.trim() || busy || (requiresSource && !sourceAssetIds.length)) {
    return false;
  }
  return actionType !== "inpaint" || Boolean(maskAssetId);
}
