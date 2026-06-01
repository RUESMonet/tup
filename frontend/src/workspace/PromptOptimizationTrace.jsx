import { CheckCircle2, CircleDot, WandSparkles } from "lucide-react";

const FIELD_LABELS = {
  subject: "主体",
  environment: "环境",
  style: "风格关键词",
  lighting: "光影关键词",
  camera_and_composition: "镜头与构图",
  atmosphere: "氛围",
  color_palette: "色彩",
  text_and_logo_constraints: "文字与 Logo 约束",
  constraints: "关键约束",
  negative_prompt: "负向词",
  additional_constraints: "补充约束",
  pattern_principles: "参考原则",
  quality_requirements: "质量要求",
  revision_focus: "修正重点",
};

const SELECTED_TERM_LABELS = {
  style: "风格",
  lighting: "光影",
  camera_and_composition: "镜头",
  atmosphere: "氛围",
  constraints: "约束",
};

export function PromptOptimizationTrace({ trace }) {
  if (!trace?.stages?.length) {
    return null;
  }

  return (
    <section className="prompt-trace">
      <div className="prompt-trace-summary">
        <div>
          <strong>优化关键词生成逻辑</strong>
          <span>展示系统如何评估原始描述、选择关键词并根据视觉结果迭代修正。</span>
        </div>
        <div className="prompt-chip-list compact">
          <span className="prompt-chip">场景：{trace.profile || "default"}</span>
          <span className="prompt-chip">参考：{trace.quality_source || "quality reference"}</span>
        </div>
      </div>

      <div className="prompt-trace-timeline">
        {trace.stages.map((stage, index) => (
          <TraceStage key={`${stage.stage}-${index}`} stage={stage} index={index} />
        ))}
      </div>
    </section>
  );
}

function TraceStage({ stage, index }) {
  const Icon = stage.stage === "prompt_refinement" || stage.stage === "visual_refinement" ? WandSparkles : stage.passed ? CheckCircle2 : CircleDot;
  const status = stage.passed === true ? "通过" : stage.passed === false ? "需优化" : stage.score == null ? "记录" : `评分 ${Number(stage.score).toFixed(1)}`;

  return (
    <article className={`prompt-trace-stage ${stage.stage}`}>
      <div className="prompt-trace-stage-header">
        <span className="prompt-trace-step">
          <Icon size={16} />
          {index + 1}
        </span>
        <div>
          <strong>{stage.title}</strong>
          {stage.summary ? <p>{stage.summary}</p> : null}
        </div>
        <span className="prompt-trace-status">{status}</span>
      </div>

      <StageDetails stage={stage} />
    </article>
  );
}

function StageDetails({ stage }) {
  return (
    <div className="prompt-trace-body">
      {stage.missing?.length ? <ChipSection title="缺失项" items={stage.missing} tone="warning" /> : null}
      {stage.defects?.length ? <ChipSection title="视觉缺陷" items={stage.defects} tone="danger" /> : null}
      {stage.suggestion ? <FieldCard label="建议" value={stage.suggestion} /> : null}
      {stage.selected_terms && Object.keys(stage.selected_terms).length ? <SelectedTerms terms={stage.selected_terms} /> : null}
      {stage.prompt_payload ? <PromptPayload payload={stage.prompt_payload} /> : null}
    </div>
  );
}

function SelectedTerms({ terms }) {
  const entries = Object.entries(terms).filter(([, value]) => hasValue(value));
  if (!entries.length) {
    return null;
  }
  return (
    <div className="prompt-trace-fields">
      {entries.map(([key, value]) => (
        <FieldCard key={key} label={SELECTED_TERM_LABELS[key] || key} value={value} />
      ))}
    </div>
  );
}

function PromptPayload({ payload }) {
  const entries = Object.entries(FIELD_LABELS).filter(([key]) => hasValue(payload[key]));
  if (!entries.length) {
    return null;
  }
  return (
    <div className="prompt-trace-fields">
      {entries.map(([key, label]) => (
        <FieldCard key={key} label={label} value={payload[key]} />
      ))}
    </div>
  );
}

function ChipSection({ title, items, tone }) {
  return (
    <div className="prompt-chip-section">
      <span>{title}</span>
      <div className="prompt-chip-list">
        {items.map((item) => (
          <span className={`prompt-chip ${tone || ""}`} key={String(item)}>
            {String(item)}
          </span>
        ))}
      </div>
    </div>
  );
}

function FieldCard({ label, value }) {
  return (
    <div className="prompt-trace-field">
      <span>{label}</span>
      {Array.isArray(value) ? (
        <div className="prompt-chip-list">
          {value.map((item, index) => (
            <span className="prompt-chip" key={`${String(item)}-${index}`}>
              {String(item)}
            </span>
          ))}
        </div>
      ) : (
        <p>{String(value)}</p>
      )}
    </div>
  );
}

function hasValue(value) {
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return value !== null && value !== undefined && value !== "";
}
