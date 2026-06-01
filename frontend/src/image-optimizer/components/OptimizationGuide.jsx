import { AlertCircle, Copy } from "lucide-react";

export function OptimizationGuide({ guide, onCopy }) {
  if (!guide) {
    return (
      <div className="optimization-guide empty">
        <AlertCircle size={20} />
        <span>点击魔法棒分析当前提示词后会生成优化指南。</span>
      </div>
    );
  }

  return (
    <section className="optimization-guide">
      <div className="guide-header">
        <div>
          <strong>优化指南</strong>
          <p>{guide.summary}</p>
        </div>
        <button type="button" className="icon-button" onClick={onCopy} title="复制优化指南">
          <Copy size={17} />
        </button>
      </div>

      {guide.issues?.length ? (
        <div className="guide-section">
          <span>主要问题</span>
          <div className="guide-list">
            {guide.issues.map((issue) => (
              <article key={`${issue.dimension}-${issue.title}`} className={`guide-issue ${issue.severity}`}>
                <strong>{issue.title}</strong>
                <p>{issue.detail}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {guide.actions?.length ? (
        <div className="guide-section">
          <span>建议动作</span>
          <div className="guide-list">
            {guide.actions.map((action) => (
              <article key={`${action.priority}-${action.title}`} className="guide-action">
                <strong>{action.title}</strong>
                <p>{action.instruction}</p>
                {action.example ? <em>{action.example}</em> : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {guide.next_steps?.length ? (
        <div className="guide-next-steps">
          <span>下一步</span>
          <ol>
            {guide.next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
