import { useCallback, useEffect, useMemo, useState } from "react";
import { ImagePlus } from "lucide-react";

import { PromptEditorPanel } from "./image-optimizer/components/PromptEditorPanel";
import { ReferencePanel } from "./image-optimizer/components/ReferencePanel";
import { ResultPanel } from "./image-optimizer/components/ResultPanel";
import { StatusPill } from "./image-optimizer/components/StatusPill";
import { defaultPrompt } from "./image-optimizer/constants";
import { useClipboardActions } from "./image-optimizer/hooks/useClipboardActions";
import { useImageGenerationTask } from "./image-optimizer/hooks/useImageGenerationTask";
import { useImageModels } from "./image-optimizer/hooks/useImageModels";
import { usePromptAnalysis } from "./image-optimizer/hooks/usePromptAnalysis";
import { promptJsonText } from "./image-optimizer/promptFormatting";

export function ImageOnlyPage() {
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [activePromptPayload, setActivePromptPayload] = useState(null);
  const [threshold, setThreshold] = useState(8);
  const [maxIter, setMaxIter] = useState(3);
  const [skipPromptEvaluation, setSkipPromptEvaluation] = useState(false);
  const [status, setStatus] = useState({ kind: "idle", message: "图片生成就绪" });

  const { models, model, setModel, loadModels, modelsLoading } = useImageModels({ onStatus: setStatus });
  const { analysis, guide, streamedText, analyzing, analyzePrompt, clearAnalysis } = usePromptAnalysis({
    prompt,
    activePromptPayload,
    onStatus: setStatus,
    streamDraft: true,
  });
  const { task, history, running, submitting, imageSrc, generateImage, clearPolling } = useImageGenerationTask({
    prompt,
    activePromptPayload,
    model,
    threshold,
    maxIter,
    skipPromptEvaluation,
    onStatus: setStatus,
  });
  const { copyFinalPrompt, copyGuide } = useClipboardActions({ prompt, task, guide, onStatus: setStatus });
  const candidates = useMemo(() => analysis?.candidate_prompts || [], [analysis]);
  const optimizedPromptPayload = useMemo(() => analysis?.optimized_prompt || null, [analysis]);
  const optimizedPromptText = useMemo(() => streamedText || (optimizedPromptPayload ? promptJsonText(optimizedPromptPayload) : ""), [optimizedPromptPayload, streamedText]);
  const form = useMemo(
    () => ({ prompt, threshold, maxIter, skipPromptEvaluation }),
    [maxIter, prompt, skipPromptEvaluation, threshold],
  );
  const modelSelection = useMemo(() => ({ models, model, onModelChange: setModel }), [model, models, setModel]);
  const generation = useMemo(() => ({ running, analyzing, submitting }), [analyzing, running, submitting]);

  useEffect(() => {
    loadModels();
    return () => {
      clearPolling();
    };
  }, []);

  const handleUseOptimizedPrompt = useCallback(() => {
    if (!optimizedPromptPayload || !optimizedPromptText) {
      return;
    }
    setPrompt(optimizedPromptText);
    setActivePromptPayload(optimizedPromptPayload);
    clearAnalysis();
    setStatus({ kind: "ready", message: "已套用大模型优化提示词，请直接生成或继续调整" });
  }, [clearAnalysis, optimizedPromptPayload, optimizedPromptText]);

  const handleUseCandidate = useCallback(
    (candidate) => {
      const payload = candidate.optimized_prompt;
      if (!payload) {
        return;
      }
      setPrompt(promptJsonText(payload));
      setActivePromptPayload(payload);
      clearAnalysis();
      setStatus({ kind: "ready", message: "已套用候选提示词，请重新分析或直接生成" });
    },
    [clearAnalysis],
  );

  const handlePromptChange = useCallback(
    (event) => {
      setPrompt(event.target.value);
      setActivePromptPayload(null);
      clearAnalysis();
    },
    [clearAnalysis],
  );

  const actions = useMemo(
    () => ({
      onPromptChange: handlePromptChange,
      onThresholdChange: setThreshold,
      onMaxIterChange: setMaxIter,
      onSkipPromptEvaluationChange: setSkipPromptEvaluation,
      onAnalyzePrompt: analyzePrompt,
      onGenerateImage: generateImage,
      onCopyFinalPrompt: copyFinalPrompt,
    }),
    [analyzePrompt, copyFinalPrompt, generateImage, handlePromptChange],
  );

  return (
    <main className="image-only-shell">
      <section className="image-workbench">
        <header className="image-topbar">
          <div className="image-brand">
            <ImagePlus size={26} />
            <div>
              <h1>图片生成优化器</h1>
              <span>提示词分析、自动迭代和结果评分</span>
            </div>
          </div>
          <StatusPill status={status} />
        </header>

        <div className="image-layout">
          <PromptEditorPanel
            form={{ prompt, threshold, maxIter, skipPromptEvaluation }}
            modelSelection={{ models, model, onModelChange: setModel }}
            generation={{ running, analyzing, submitting }}
            actions={{
              onPromptChange: handlePromptChange,
              onThresholdChange: setThreshold,
              onMaxIterChange: setMaxIter,
              onSkipPromptEvaluationChange: setSkipPromptEvaluation,
              onAnalyzePrompt: analyzePrompt,
              onGenerateImage: generateImage,
              onCopyFinalPrompt: copyFinalPrompt,
            }}
          />

          <ResultPanel imageSrc={imageSrc} running={running} task={task} />
        </div>

        <ReferencePanel
          guide={guide}
          analysis={analysis}
          optimizedPromptText={optimizedPromptText}
          candidates={candidates}
          history={history}
          modelsLoading={modelsLoading}
          onCopyGuide={copyGuide}
          onReloadModels={loadModels}
          onUseOptimizedPrompt={handleUseOptimizedPrompt}
          onUseCandidate={handleUseCandidate}
        />
      </section>
    </main>
  );
}
