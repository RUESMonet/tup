import { useEffect, useMemo, useRef, useState } from "react";

import { createGenerationTask, fetchTask, fetchTaskHistory, isAbortError, requestErrorMessage } from "../api";
import { POLL_INTERVAL_MS, terminalStatuses } from "../constants";
import { promptForRequest } from "../promptFormatting";
import { imageSource, normalizeNumber } from "../taskUtils";

export function useImageGenerationTask({ prompt, activePromptPayload, model, threshold, maxIter, skipPromptEvaluation, onStatus }) {
  const [task, setTask] = useState(null);
  const [history, setHistory] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const pollRef = useRef(null);
  const requestRef = useRef(null);

  const running = Boolean(task && !terminalStatuses.has(task.status));
  const imageSrc = useMemo(() => imageSource(task), [task]);

  useEffect(
    () => () => {
      clearPolling();
      abortActiveRequest();
    },
    [],
  );

  async function generateImage() {
    if (!prompt.trim() || running || submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    clearPolling();
    abortActiveRequest();
    setTask(null);
    setHistory([]);
    onStatus({ kind: "loading", message: "正在提交图片生成任务" });
    try {
      const payload = await runWithSignal((signal) =>
        createGenerationTask(
          {
            input: promptForRequest(prompt, activePromptPayload),
            model,
            threshold: normalizeNumber(threshold, 8),
            max_iter: normalizeNumber(maxIter, 3),
            skip_prompt_evaluation: skipPromptEvaluation,
          },
          { signal },
        ),
      );
      updateTask({ task_id: payload.task_id, status: payload.status });
      onStatus({ kind: "loading", message: "图片生成中" });
      const done = await pollTaskSafely(payload.task_id);
      if (!done) {
        startPolling(payload.task_id);
      }
    } catch (error) {
      clearPolling();
      if (!isAbortError(error)) {
        onStatus({ kind: "failed", message: requestErrorMessage(error, "图片生成提交失败") });
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  function clearPolling() {
    if (pollRef.current) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }

  function abortActiveRequest() {
    requestRef.current?.abort();
    requestRef.current = null;
  }

  async function runWithSignal(operation) {
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      return await operation(controller.signal);
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
      }
    }
  }

  async function pollTask(taskId) {
    const payload = await runWithSignal((signal) => fetchTask(taskId, { signal }));
    updateTask(payload);
    if (!terminalStatuses.has(payload.status)) {
      return false;
    }

    clearPolling();
    if (payload.status === "succeeded") {
      onStatus({ kind: "ready", message: "图片生成完成" });
      try {
        const historyPayload = await runWithSignal((signal) => fetchTaskHistory(taskId, { signal }));
        setHistory(historyPayload.history || []);
      } catch (error) {
        if (!isAbortError(error)) {
          onStatus({ kind: "ready", message: "图片生成完成，迭代历史加载失败" });
        }
      }
      return true;
    }
    onStatus({ kind: "failed", message: payload.error || "图片生成失败" });
    return true;
  }

  async function pollTaskSafely(taskId) {
    try {
      return await pollTask(taskId);
    } catch (error) {
      clearPolling();
      if (!isAbortError(error)) {
        onStatus({ kind: "failed", message: requestErrorMessage(error, "任务查询失败") });
      }
      return true;
    }
  }

  function startPolling(taskId) {
    async function tick() {
      const done = await pollTaskSafely(taskId);
      if (!done) {
        pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    }

    pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
  }

  function updateTask(nextTask) {
    setTask((currentTask) => (sameTaskView(currentTask, nextTask) ? currentTask : nextTask));
  }

  return { task, history, running, submitting, imageSrc, generateImage, clearPolling };
}

function sameTaskView(currentTask, nextTask) {
  if (!currentTask || !nextTask) {
    return currentTask === nextTask;
  }

  return (
    currentTask.task_id === nextTask.task_id &&
    currentTask.status === nextTask.status &&
    currentTask.error === nextTask.error &&
    currentTask.image_url === nextTask.image_url &&
    currentTask.image_b64_json === nextTask.image_b64_json &&
    currentTask.image_media_type === nextTask.image_media_type &&
    currentTask.final_prompt === nextTask.final_prompt &&
    currentTask.score === nextTask.score &&
    currentTask.iterations === nextTask.iterations
  );
}
