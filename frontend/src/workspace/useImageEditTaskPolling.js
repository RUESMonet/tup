import { useEffect } from "react";

import { fetchProjectTasks } from "../api/projects";

export function useImageEditTaskPolling({ canvas, pendingImageEditTasks, setPendingImageEditTasks, projectId, refreshCanvasArtifacts, onComplete, onStatus }) {
  useEffect(() => {
    const pendingEntries = Object.entries(pendingImageEditTasks);
    if (!canvas?.id || !pendingEntries.length) {
      return undefined;
    }
    const editedTaskIdsOnCanvas = new Set((canvas.nodes || []).filter((node) => node.type === "edited_image" || node.payload?.source === "canvas_image_edit").map((node) => node.payload?.task_id).filter(Boolean));
    const completedEntries = pendingEntries.filter(([taskId]) => editedTaskIdsOnCanvas.has(taskId));
    if (completedEntries.length) {
      setPendingImageEditTasks((current) => Object.fromEntries(Object.entries(current).filter(([taskId]) => !editedTaskIdsOnCanvas.has(taskId))));
      onStatus?.({ kind: "ready", message: "图片编辑结果已回写到画布" });
      if (completedEntries.length === pendingEntries.length) {
        return undefined;
      }
    }
    const timer = window.setTimeout(async () => {
      try {
        await refreshCanvasArtifacts();
        const taskList = await fetchProjectTasks(projectId);
        const tasksById = new Map((taskList.tasks || []).map((task) => [task.task_id, task]));
        setPendingImageEditTasks((current) => Object.fromEntries(Object.entries(current).filter(([taskId]) => tasksById.get(taskId)?.status !== "failed").map(([taskId, task]) => [taskId, { ...task, attempts: task.attempts + 1 }])));
        if (Object.keys(pendingImageEditTasks).some((taskId) => tasksById.get(taskId)?.status === "failed")) {
          onStatus?.({ kind: "failed", message: "图片编辑失败，请检查任务历史或模型配置" });
        }
        await onComplete?.();
      } catch (error) {
        onStatus?.({ kind: "failed", message: error?.message || "图片编辑结果刷新失败" });
      }
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [canvas?.id, canvas?.nodes, pendingImageEditTasks, projectId, refreshCanvasArtifacts, setPendingImageEditTasks, onComplete, onStatus]);
}
