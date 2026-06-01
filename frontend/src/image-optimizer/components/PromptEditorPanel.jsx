import { Copy, Loader2, Sparkles, WandSparkles } from "lucide-react";

export function PromptEditorPanel({ form, modelSelection, generation, actions }) {
  const { prompt, threshold, maxIter, skipPromptEvaluation } = form;
  const { models, model, onModelChange } = modelSelection;
  const { running, analyzing, submitting } = generation;
  const generating = running || submitting;
  const controlsDisabled = generating;
  const promptLength = prompt.trim().length;
  const {
    onPromptChange,
    onThresholdChange,
    onMaxIterChange,
    onSkipPromptEvaluationChange,
    onAnalyzePrompt,
    onGenerateImage,
    onCopyFinalPrompt,
  } = actions;

  return (
    <section className="image-editor-panel">
      <div className="panel-heading">
        <div>
          <strong>提示词</strong>
          <span>描述主体、画面、风格、构图和需要避免的问题</span>
        </div>
        <div className="panel-actions">
          <button
            type="button"
            className="icon-button"
            onClick={onAnalyzePrompt}
            disabled={!prompt.trim() || analyzing || generating}
            title={analyzing ? "正在分析提示词" : "分析当前提示词"}
            aria-label={analyzing ? "正在分析提示词" : "分析当前提示词"}
          >
            {analyzing ? <Loader2 className="spinning" size={18} /> : <WandSparkles size={18} />}
          </button>
          <button type="button" className="primary-image-action compact" onClick={onGenerateImage} disabled={!prompt.trim() || generating || analyzing}>
            {generating ? <Loader2 className="spinning" size={18} /> : <Sparkles size={18} />}
            <span>{generating ? "生成中" : "生成图片"}</span>
          </button>
        </div>
      </div>

      <textarea value={prompt} onChange={onPromptChange} spellCheck={false} aria-label="图片生成提示词" />
      <div className="prompt-meta">
        <span>{promptLength ? `已输入 ${promptLength} 个字符` : "输入提示词后可分析或生成"}</span>
        {activePromptHint(promptLength)}
      </div>

      <div className="image-controls">
        <label>
          <span>模型</span>
          <select value={model} onChange={(event) => onModelChange(event.target.value)} disabled={controlsDisabled}>
            {models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id} {item.configured ? "" : "(未配置)"}
              </option>
            ))}
          </select>
          <small className="field-help">选择当前图片生成任务使用的模型。</small>
        </label>
        <label>
          <span>目标评分</span>
          <input type="number" min="0" max="10" step="0.5" value={threshold} onChange={(event) => onThresholdChange(event.target.value)} disabled={controlsDisabled} />
          <small className="field-help">达到目标评分后会停止继续迭代。</small>
        </label>
        <label>
          <span>迭代次数</span>
          <input type="number" min="1" max="10" value={maxIter} onChange={(event) => onMaxIterChange(event.target.value)} disabled={controlsDisabled} />
          <small className="field-help">设置最多尝试优化的轮数。</small>
        </label>
      </div>

      <label className="image-toggle">
        <input type="checkbox" checked={skipPromptEvaluation} onChange={(event) => onSkipPromptEvaluationChange(event.target.checked)} disabled={controlsDisabled} />
        <span>跳过生成前提示词评分</span>
      </label>

      <div className="image-action-row">
        <button type="button" className="secondary-image-action" onClick={onCopyFinalPrompt}>
          <Copy size={17} />
          <span>复制提示词</span>
        </button>
      </div>
    </section>
  );
}

function activePromptHint(promptLength) {
  if (promptLength < 40) {
    return <span>建议补充主体、环境和风格细节。</span>;
  }
  return <span>可继续分析质量或直接生成。</span>;
}
