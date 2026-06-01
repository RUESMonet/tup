import { useEffect } from "react";

import { fetchProjectTasks } from "../api/projects";

export function useVideoTaskPolling({ canvas, pendingVideoTasks, setPendingVideoTasks, projectId, refreshCanvasArtifacts, onComplete, onStatus }) {
  useEffect(() => {
    const pendingEntries = Object.entries(pendingVideoTasks);
    if (!canvas?.id || !pendingEntries.length) {
      return undefined;
    }
    const videoTaskIdsOnCanvas = new Set((canvas.nodes || []).filter((node) => node.type === "generated_video").map((node) => node.payload?.task_id).filter(Boolean));
    const completedEntries = pendingEntries.filter(([taskId]) => videoTaskIdsOnCanvas.has(taskId));
    if (completedEntries.length) {
      setPendingVideoTasks((current) => Object.fromEntries(Object.entries(current).filter(([taskId]) => !videoTaskIdsOnCanvas.has(taskId))));
      onStatus?.({ kind: "ready", message: "视频结果已回写到画布" });
      if (completedEntries.length === pendingEntries.length) {
        return undefined;
      }
    }
    const timer = window.setTimeout(async () => {
      try {
        await refreshCanvasArtifacts();
        const taskList = await fetchProjectTasks(projectId);
        const tasksById = new Map((taskList.tasks || []).map((task) => [task.task_id, task]));
        setPendingVideoTasks((current) => Object.fromEntries(Object.entries(current).filter(([taskId]) => tasksById.get(taskId)?.status !== "failed").map(([taskId, task]) => [taskId, { ...task, attempts: task.attempts + 1 }])));
        if (Object.keys(pendingVideoTasks).some((taskId) => tasksById.get(taskId)?.status === "failed")) {
          onStatus?.({ kind: "failed", message: "视频任务失败，请检查任务历史或模型配置" });
        }
        await onComplete?.();
      } catch (error) {
        onStatus?.({ kind: "failed", message: error?.message || "视频结果刷新失败" });
      }
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [canvas?.id, canvas?.nodes, pendingVideoTasks, projectId, refreshCanvasArtifacts, setPendingVideoTasks, onComplete, onStatus]);
}
