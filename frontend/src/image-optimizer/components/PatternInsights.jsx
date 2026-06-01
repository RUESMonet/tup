export function PatternInsights({ analysis }) {
  if (!analysis) {
    return null;
  }

  const patterns = analysis.matched_patterns || [];
  const principles = analysis.pattern_principles || [];
  return (
    <section className="pattern-insights">
      <div className="pattern-summary">
        <div>
          <strong>学习到的参考模式</strong>
          <p>
            当前识别为 {analysis.quality?.profile || "default"} 场景，匹配置信度 {Math.round((analysis.profile_confidence || 0) * 100)}%。
          </p>
        </div>
        <span>{analysis.source_freshness?.case_count || 0} 个参考案例</span>
      </div>

      {patterns.length ? (
        <div className="pattern-card-grid">
          {patterns.slice(0, 3).map((pattern) => (
            <article key={pattern.id}>
              <strong>{pattern.title}</strong>
              <span>{pattern.source_case}</span>
              <p>{(pattern.principles || []).slice(0, 2).join(" / ")}</p>
            </article>
          ))}
        </div>
      ) : null}

      {principles.length ? (
        <div className="principle-list">
          <span>提炼原则</span>
          <ul>
            {principles.slice(0, 5).map((principle) => (
              <li key={principle}>{principle}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
