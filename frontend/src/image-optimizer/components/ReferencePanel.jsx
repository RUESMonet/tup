import { useState } from "react";
import { AlertCircle, CheckCircle2, RefreshCw } from "lucide-react";

import { readablePromptText, summarizeCandidate } from "../promptFormatting";
import { OptimizationGuide } from "./OptimizationGuide";
import { PatternInsights } from "./PatternInsights";

const COLLAPSED_HISTORY_COUNT = 3;

export function ReferencePanel({
  guide,
  analysis,
  optimizedPromptText,
  candidates,
  history,
  modelsLoading,
  onCopyGuide,
  onReloadModels,
  onUseOptimizedPrompt,
  onUseCandidate,
}) {
  const [showAllHistory, setShowAllHistory] = useState(false);
  const visibleHistory = showAllHistory ? history : history.slice(-COLLAPSED_HISTORY_COUNT);
  const hiddenHistoryCount = Math.max(history.length - visibleHistory.length, 0);

  return (
    <section className="image-reference-panel">
      <div className="panel-heading">
        <div>
          <strong>优化建议</strong>
          <span>可直接套用候选提示词，或查看每次迭代记录</span>
        </div>
        <button type="button" className="icon-button" onClick={onReloadModels} disabled={modelsLoading} title="重新加载模型" aria-label="重新加载模型">
          <RefreshCw className={modelsLoading ? "spinning" : ""} size={18} />
        </button>
      </div>

      <OptimizationGuide guide={guide} onCopy={onCopyGuide} />
      <PatternInsights analysis={analysis} />

      {optimizedPromptText ? (
        <div className="optimized-prompt-preview">
          <div className="section-kicker">
            <strong>优化后的 JSON 提示词</strong>
            <span>由当前提示词和参考数据生成</span>
          </div>
          <pre>{optimizedPromptText}</pre>
          <div className="optimized-prompt-actions">
            <button className="primary-image-action compact" type="button" onClick={onUseOptimizedPrompt}>
              套用优化提示词
            </button>
          </div>
        </div>
      ) : null}

      <div className="section-kicker">
        <strong>可套用候选</strong>
        <span>{candidates.length ? `${candidates.length} 个候选方案` : "等待提示词分析"}</span>
      </div>
      <div className="candidate-grid">
        {candidates.length ? (
          candidates.map((candidate) => {
            const summary = candidate.description || summarizeCandidate(candidate);
            const title = candidate.title || candidate.id;
            return (
              <button type="button" key={candidate.id} onClick={() => onUseCandidate(candidate)} title={summary} aria-label={`套用候选提示词：${title}`}>
                <strong>{title}</strong>
                <span>{summary}</span>
              </button>
            );
          })
        ) : (
          <div className="reference-empty">
            <AlertCircle size={20} />
            <span>点击魔法棒分析当前提示词后会出现候选方案。</span>
          </div>
        )}
      </div>

      {history.length ? (
        <div className="iteration-section">
          <div className="section-kicker">
            <strong>生成过程记录</strong>
            <span>{hiddenHistoryCount ? `显示最近 ${visibleHistory.length} 条，已收起 ${hiddenHistoryCount} 条` : `${history.length} 条记录`}</span>
          </div>
          <div className="iteration-list">
            {visibleHistory.map((item) => (
              <article key={item.iteration}>
                <CheckCircle2 size={18} />
                <div>
                  <strong>
                    第 {item.iteration} 轮 · {item.score == null ? "未评分" : Number(item.score).toFixed(1)}
                  </strong>
                  <p>{readablePromptText(item.prompt)}</p>
                </div>
              </article>
            ))}
          </div>
          {history.length > COLLAPSED_HISTORY_COUNT ? (
            <button type="button" className="iteration-toggle" onClick={() => setShowAllHistory((value) => !value)}>
              {showAllHistory ? "收起历史" : "显示全部历史"}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
