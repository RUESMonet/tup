import { useEffect, useRef, useState } from "react";

import { fetchProjectTask, fetchProjectTaskHistory } from "../api/generation";
import { isAbortError, requestErrorMessage } from "../api/client";
import { POLL_INTERVAL_MS, terminalStatuses } from "../image-optimizer/constants";

export function useProjectGenerationTask({ createTask, onStatus, onComplete }) {
  const [task, setTask] = useState(null);
  const [history, setHistory] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const pollRef = useRef(null);
  const requestRef = useRef(null);
  const running = Boolean(task && !terminalStatuses.has(task.status));

  useEffect(
    () => () => {
      clearPolling();
      abortActiveRequest();
    },
    [],
  );

  async function submit(payload, label) {
    if (submittingRef.current || running) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setTask(null);
    setHistory([]);
    clearPolling();
    abortActiveRequest();
    onStatus({ kind: "loading", message: `正在提交${label}任务` });
    try {
      const response = await createTask(payload);
      setTask({ task_id: response.task_id, status: response.status });
      onStatus({ kind: "loading", message: `${label}生成中` });
      const done = await pollTask(response.task_id, label);
      if (!done) {
        startPolling(response.task_id, label);
      }
    } catch (error) {
      if (!isAbortError(error)) {
        onStatus({ kind: "failed", message: requestErrorMessage(error, `${label}生成提交失败`) });
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  async function pollTask(taskId, label) {
    try {
      const payload = await runWithSignal((signal) => fetchProjectTask(taskId, { signal }));
      setTask(payload);
      if (!terminalStatuses.has(payload.status)) {
        return false;
      }
      clearPolling();
      if (payload.status === "succeeded") {
        onStatus({ kind: "ready", message: `${label}生成完成` });
        const historyPayload = await runWithSignal((signal) => fetchProjectTaskHistory(taskId, { signal }));
        setHistory(historyPayload.history || []);
        onComplete?.(payload);
        return true;
      }
      onStatus({ kind: "failed", message: payload.error || `${label}生成失败` });
      return true;
    } catch (error) {
      clearPolling();
      if (!isAbortError(error)) {
        onStatus({ kind: "failed", message: requestErrorMessage(error, "任务查询失败") });
      }
      return true;
    }
  }

  function startPolling(taskId, label) {
    async function tick() {
      const done = await pollTask(taskId, label);
      if (!done) {
        pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    }
    pollRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
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

  return { task, history, running, submitting, submit };
}
