import { AlertCircle, ImagePlus, Loader2 } from "lucide-react";

import { readablePromptText } from "../promptFormatting";
import { Metric } from "./Metric";

export function ResultPanel({ imageSrc, running, task }) {
  const error = task?.error;
  const emptyText = error ? "生成失败，请查看错误信息" : running ? "正在等待图片结果" : "生成结果会显示在这里";

  return (
    <section className="image-result-panel">
      <div className={`result-frame${error ? " failed" : ""}`}>
        {imageSrc ? (
          <img src={imageSrc} alt="生成结果" decoding="async" />
        ) : (
          <div className={`result-empty${error ? " failed" : ""}`}>
            {error ? <AlertCircle size={34} /> : running ? <Loader2 className="spinning" size={34} /> : <ImagePlus size={38} />}
            <span>{emptyText}</span>
          </div>
        )}
      </div>

      {error ? <div className="result-error">{error}</div> : null}

      <dl className="result-stats">
        <Metric label="状态" value={task?.status || "idle"} />
        <Metric label="评分" value={task?.score == null ? "-" : Number(task.score).toFixed(1)} />
        <Metric label="迭代" value={task?.iterations || "-"} />
      </dl>

      {task?.final_prompt ? (
        <div className="final-prompt">
          <strong>最终提示词</strong>
          <pre>{readablePromptText(task.final_prompt)}</pre>
        </div>
      ) : null}
    </section>
  );
}
