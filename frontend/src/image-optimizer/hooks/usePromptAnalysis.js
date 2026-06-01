import { useEffect, useRef, useState } from "react";

import { analyzeReferencePrompt, isAbortError, requestErrorMessage, streamReferencePromptDraft } from "../api";
import { promptForRequest } from "../promptFormatting";

export function usePromptAnalysis({ prompt, activePromptPayload, onStatus, streamDraft = false }) {
  const [analysis, setAnalysis] = useState(null);
  const [guide, setGuide] = useState(null);
  const [streamedText, setStreamedText] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const analyzingRef = useRef(false);
  const requestRef = useRef(null);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [prompt, activePromptPayload],
  );

  async function analyzePrompt() {
    if (!prompt.trim() || analyzingRef.current) {
      return;
    }

    analyzingRef.current = true;
    setAnalyzing(true);
    const controller = new AbortController();
    requestRef.current = controller;
    onStatus({ kind: "loading", message: "正在分析提示词" });

    try {
      const requestPrompt = promptForRequest(prompt, activePromptPayload);
      if (streamDraft) {
        const referenceAnalysis = analyzeReferencePrompt({ prompt: requestPrompt, defects: [] }, { signal: controller.signal });
        await optimizeWithStreaming(requestPrompt, controller.signal, referenceAnalysis);
      } else {
        const payload = await analyzeReferencePrompt({ prompt: requestPrompt, defects: [] }, { signal: controller.signal });
        setStreamedText("");
        setAnalysis(payload);
        setGuide(payload.guide || null);
        onStatus({ kind: "ready", message: "提示词分析完成" });
      }
    } catch (error) {
      if (!isAbortError(error)) {
        if (!streamDraft) {
          onStatus({ kind: "failed", message: requestErrorMessage(error, "提示词分析失败") });
          return;
        }
        setAnalysis(null);
        setGuide(null);
        setStreamedText("");
        onStatus({ kind: "failed", message: requestErrorMessage(error, "大模型提示词优化失败") });
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        analyzingRef.current = false;
        setAnalyzing(false);
      }
    }
  }

  async function optimizeWithStreaming(requestPrompt, signal, referenceAnalysis) {
    let nextStreamedText = "";
    setAnalysis(null);
    setGuide(null);
    setStreamedText("");
    onStatus({ kind: "loading", message: "正在流式优化提示词" });

    const finalEvent = await streamReferencePromptDraft(
      { prompt: requestPrompt },
      {
        signal,
        onEvent: (event) => {
          if (event.type === "error") {
            throw new Error(event.error || "提示词流式优化失败");
          }
          if (event.type === "delta" && typeof event.delta === "string") {
            nextStreamedText += event.delta;
            setStreamedText(nextStreamedText);
            setAnalysis(buildDraftAnalysis(requestPrompt, nextStreamedText));
          }
          if (event.type === "done" && typeof event.draft_prompt === "string") {
            nextStreamedText = event.draft_prompt;
            setStreamedText(nextStreamedText);
            setAnalysis(buildDraftAnalysis(requestPrompt, nextStreamedText));
          }
        },
      },
    );

    if (!nextStreamedText.trim() && typeof finalEvent?.draft_prompt === "string") {
      nextStreamedText = finalEvent.draft_prompt;
      setStreamedText(nextStreamedText);
      setAnalysis(buildDraftAnalysis(requestPrompt, nextStreamedText));
    }
    if (!nextStreamedText.trim()) {
      throw new Error("提示词流式优化未返回内容");
    }
    const referencePayload = await referenceAnalysis;
    const draftAnalysis = buildDraftAnalysis(requestPrompt, nextStreamedText);
    setGuide(referencePayload.guide || null);
    setAnalysis({
      ...referencePayload,
      optimized_prompt: draftAnalysis.optimized_prompt,
      optimizer: draftAnalysis.optimizer,
    });
    onStatus({ kind: "ready", message: "提示词流式优化完成" });
  }

  function clearAnalysis() {
    setAnalysis(null);
    setGuide(null);
    setStreamedText("");
  }

  return { analysis, guide, streamedText, analyzing, analyzePrompt, clearAnalysis };
}

function buildDraftAnalysis(originalPrompt, nextStreamedText) {
  const cleanDraft = nextStreamedText.trim();
  return {
    optimized_prompt: {
      task: "image_generation",
      source: "stream_draft",
      original_prompt: originalPrompt,
      profile: "draft",
      optimization_hints: [],
      prompt: { raw_text: cleanDraft },
      reference_usage: {
        used_quality_dimensions: [],
        used_pattern_ids: [],
        candidate_strategy: "streamed prompt draft",
      },
    },
    optimizer: {
      source: "stream",
      fallback: false,
      error: null,
    },
  };
}
