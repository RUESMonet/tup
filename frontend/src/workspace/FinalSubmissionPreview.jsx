const MEDIA_TYPE_LABELS = {
  edited_image: "Edited Image",
  generated_video: "Generated Video",
  selected_image: "Selected Image",
  generated_image: "Generated Image",
};

export function FinalSubmissionPreview({ submission }) {
  const lineage = submission.production_lineage || {};
  const approvalSummary = lineage.approval_summary || {};
  const approvedMedia = approvedProductionMedia(lineage).slice(0, 6);
  return (
    <div className="canvas-final-preview">
      <div>
        <span>Artifact</span>
        <strong>{submission.artifact?.id?.slice(0, 8) || "已保存"}</strong>
      </div>
      <div>
        <span>@文件</span>
        <strong>{submission.asset_references?.length || 0} 个引用</strong>
      </div>
      <div>
        <span>Task</span>
        <strong>{submission.task?.task_id ? submission.task.task_id.slice(0, 8) : "未生成"}</strong>
      </div>
      <div>
        <span>Active Path</span>
        <strong>{lineage.active_production_path?.status === "active" ? `${lineage.active_production_path.selection_strategy === "designer_pinned" ? "Pinned" : "Auto"} · ${lineage.active_production_path.version_count || 0} versions · ${formatScore(lineage.active_production_path.score_end)}` : "未选择"}</strong>
      </div>
      <div>
        <span>Governance</span>
        <strong>{lineage.branch_operation_log?.latest_operations?.length || 0} ops · {lineage.branch_operation_log?.latest_pin ? "Pinned" : "No pin"} · {approvalSummary.approved_count || 0} approved</strong>
      </div>
      <PromptSpecBlueprintPreview spec={submission.prompt_spec} finalPrompt={submission.final_prompt} />
      <section className="canvas-approved-media-summary" aria-label="Approved production media">
        <div>
          <span>Approved Production Media</span>
          <strong>{approvalSummary.approved_count || approvedMedia.length || 0} approved · {approvalSummary.approved_edited_images || 0} images · {approvalSummary.approved_videos || 0} videos</strong>
          <small>Latest approve: {operationTargetLabel(approvalSummary.latest_approve)} · latest revoke: {operationTargetLabel(approvalSummary.latest_revoke)}</small>
        </div>
        <div className="canvas-approved-media-list">
          {approvedMedia.map((item) => (
            <article className="canvas-approved-media-card" key={item.id || item.node_id || item.asset_id}>
              <span>{MEDIA_TYPE_LABELS[item.type] || item.type || "Media"}</span>
              <strong>{String(item.id || item.node_id || item.asset_id || "media").slice(0, 8)} · asset {String(item.asset_id || "—").slice(0, 8)}</strong>
              <small>{item.approved_at ? formatDate(item.approved_at) : "已批准"}</small>
              {item.approval_reason ? <p>{trimText(item.approval_reason, 120)}</p> : null}
            </article>
          ))}
          {!approvedMedia.length ? <small>当前 Final JSON 中还没有已批准生产媒体。</small> : null}
        </div>
      </section>
      <pre>{JSON.stringify(submission, null, 2)}</pre>
    </div>
  );
}

function PromptSpecBlueprintPreview({ spec, finalPrompt }) {
  if (!spec) {
    return null;
  }
  const cases = spec.case_strategy?.selected_cases || [];
  const principles = spec.case_strategy?.visual_principles || [];
  const sections = promptSectionList(spec.final_prompt_sections, finalPrompt);
  const dnaCards = promptSpecDnaCards(spec);
  return (
    <section className="canvas-prompt-spec-blueprint" aria-label="Prompt Spec creative blueprint">
      <div className="canvas-prompt-spec-heading">
        <div>
          <span>Prompt Spec 创作蓝图</span>
          <strong>{spec.generation_plan?.compiler || "case-aware compiler"} · {spec.generation_plan?.case_count || cases.length || 0} cases</strong>
        </div>
        <small>{spec.creative_direction?.concept_source || "画布图谱 + 案例 DNA + 专业质量参考"}</small>
      </div>
      <div className="canvas-prompt-dna-grid">
        {dnaCards.map((item) => (
          <article key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value || "等待编译"}</strong>
            {item.meta ? <small>{item.meta}</small> : null}
          </article>
        ))}
      </div>
      {cases.length ? (
        <div className="canvas-case-inspiration-list" aria-label="Selected case inspirations">
          {cases.slice(0, 4).map((item) => (
            <article key={item.case_id || item.title}>
              <span>{item.profile || "case"}</span>
              <strong>{item.title || item.case_id || "Untitled case"}</strong>
              <small>{item.creative_strategy || caseDnaSummary(item.transferable_dna) || "transferable visual DNA"}</small>
            </article>
          ))}
        </div>
      ) : null}
      {principles.length ? (
        <ul className="canvas-prompt-principles">
          {principles.slice(0, 6).map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      {sections.length ? (
        <div className="canvas-final-prompt-sections">
          <span>Designer-facing prompt sections</span>
          {sections.slice(0, 8).map((section, index) => (
            <p key={`${index}-${section.slice(0, 24)}`}>{section}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function promptSpecDnaCards(spec) {
  const textSystem = spec.text_system || {};
  const requiredText = Array.isArray(textSystem.required_text) ? textSystem.required_text.join(" / ") : "";
  return [
    {
      label: "Creative Direction",
      value: spec.creative_direction?.default_quality_direction || spec.creative_direction?.core_brief,
      meta: spec.creative_direction?.target_profile,
    },
    {
      label: "Composition",
      value: spec.composition?.layout,
      meta: spec.composition?.camera,
    },
    {
      label: "Lighting / Material",
      value: spec.style_system?.lighting,
      meta: listPreview(spec.style_system?.materials, 3),
    },
    {
      label: "Text / Quality Gate",
      value: requiredText || listPreview(spec.constraints?.quality_gates, 2),
      meta: listPreview(spec.constraints?.avoid, 2),
    },
  ];
}

function promptSectionList(sections, fallbackPrompt) {
  if (Array.isArray(sections) && sections.length) {
    return sections.map((item) => String(item || "").trim()).filter(Boolean);
  }
  return splitPromptSections(fallbackPrompt);
}

function splitPromptSections(prompt) {
  return String(prompt || "").split("\n").map((item) => item.trim()).filter(Boolean);
}

function caseDnaSummary(dna) {
  if (!dna || typeof dna !== "object") {
    return "";
  }
  return Object.entries(dna)
    .filter(([, value]) => Array.isArray(value) ? value.length : Boolean(value))
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.slice(0, 2).join(" / ") : value}`)
    .join(" · ");
}

function listPreview(value, limit) {
  return Array.isArray(value) ? value.slice(0, limit).join(" / ") : "";
}

function approvedProductionMedia(lineage) {
  const explicit = Array.isArray(lineage.approved_production_media) ? lineage.approved_production_media : [];
  if (explicit.length) {
    return explicit;
  }
  const edited = Array.isArray(lineage.edited_images) ? lineage.edited_images : [];
  const videos = Array.isArray(lineage.video_outputs) ? lineage.video_outputs : [];
  return [...edited, ...videos].filter((item) => item?.approval_status === "approved");
}

function operationTargetLabel(operation) {
  if (!operation) {
    return "—";
  }
  const payload = operation.payload || {};
  return operation.target_node_id?.slice(0, 8) || (payload.candidate_id ? `candidate ${String(payload.candidate_id).slice(0, 8)}` : "") || (payload.asset_id ? `asset ${String(payload.asset_id).slice(0, 8)}` : "") || "canvas";
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatScore(score) {
  return Number.isFinite(Number(score)) ? Number(score).toFixed(1) : "—";
}

function trimText(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
