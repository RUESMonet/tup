import { useRef, useState } from "react";

import { createCanvasNode, deleteCanvasNode } from "../api/canvas";
import { uploadProjectAsset } from "../api/projects";
import { appendAssetMention, canvasPoint, NODE_SIZE, uniqueAssetMentionLabel } from "./canvasUtils";
import { assetLabel, isVideoAsset } from "./mediaUrls";

export function useCanvasAssetUpload({ canvas, creating, loadCanvas, onComplete, onStatus, projectId, referenceInstruction, referenceRole, referenceRoles, setBrief, setCanvas, setCreating, setFinalSubmission, setSelectedNodeId, setSeriesPlan, view }) {
  const [uploadingAssets, setUploadingAssets] = useState(false);
  const assetUploadInputRef = useRef(null);

  function referenceMeta(asset, roleValue, instructionValue) {
    const isVideoReference = isVideoAsset(asset);
    const effectiveRole = isVideoReference && roleValue === "product" ? "motion" : roleValue;
    const roleMeta = referenceRoles.find((role) => role.value === effectiveRole) || referenceRoles[0];
    return {
      effectiveRole,
      instruction: String(instructionValue || "").trim() || roleMeta.help,
      isVideoReference,
      roleMeta,
    };
  }

  async function createAssetReferenceNode(asset, mentionLabel, options = {}) {
    const meta = referenceMeta(asset, options.referenceRole ?? referenceRole, options.referenceInstruction ?? referenceInstruction);
    const node = await createCanvasNode(canvas.id, {
      type: "asset",
      title: `${assetLabel(asset, "参考资产")} · @${mentionLabel}`,
      position: options.position || canvasPoint(520, 180, view),
      size: NODE_SIZE,
      payload: {
        asset_id: asset.id,
        asset_kind: meta.isVideoReference ? "video" : "image",
        role: meta.isVideoReference ? "reference_video" : "reference_image",
        reference_role: meta.effectiveRole,
        reference_instruction: meta.instruction,
        mention_label: mentionLabel,
        influence_strength: meta.effectiveRole === "style" ? 0.65 : 0.85,
        media_type: asset.media_type,
        ...(meta.isVideoReference ? { video_url: asset.url } : { image_url: asset.url }),
      },
    });
    setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, node] } : current));
    setSelectedNodeId(node.id);
    setSeriesPlan(null);
    setFinalSubmission(null);
    return { node, roleMeta: meta.roleMeta };
  }

  async function addAssetNode(asset) {
    if (!canvas || creating || uploadingAssets) {
      return;
    }
    const mentionLabel = uniqueAssetMentionLabel(asset, canvas.nodes);
    setCreating(true);
    try {
      const { roleMeta } = await createAssetReferenceNode(asset, mentionLabel);
      setBrief((current) => appendAssetMention(current, mentionLabel));
      onStatus?.({ kind: "ready", message: `@${mentionLabel} 已作为${roleMeta.label}参考放入画布` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "创建资产节点失败" });
    } finally {
      setCreating(false);
    }
  }

  function canvasUploadPosition(index) {
    const origin = canvasPoint(500, 220, view);
    return { x: origin.x + (index % 2) * 340, y: origin.y + Math.floor(index / 2) * 220 };
  }

  function openCanvasAssetUpload() {
    assetUploadInputRef.current?.click();
  }

  async function uploadCanvasAssets(event) {
    const files = Array.from(event.target.files || []).slice(0, 12);
    event.target.value = "";
    if (!files.length || !canvas || uploadingAssets) {
      return;
    }
    const batchReferenceRole = referenceRole;
    const batchReferenceInstruction = referenceInstruction;
    setUploadingAssets(true);
    onStatus?.({ kind: "loading", message: `正在上传 ${files.length} 个媒体并写入画布` });
    let createdNodes = [];
    let mentionLabels = [];
    let uploadedAssets = [];
    try {
      for (const [index, file] of files.entries()) {
        const asset = await uploadProjectAsset(projectId, file);
        uploadedAssets = [...uploadedAssets, asset];
        const mentionLabel = uniqueAssetMentionLabel(asset, [...canvas.nodes, ...createdNodes]);
        const { node } = await createAssetReferenceNode(asset, mentionLabel, {
          position: canvasUploadPosition(index),
          referenceInstruction: batchReferenceInstruction,
          referenceRole: batchReferenceRole,
        });
        createdNodes = [...createdNodes, node];
        mentionLabels = [...mentionLabels, mentionLabel];
      }
      if (mentionLabels.length) {
        setBrief((current) => mentionLabels.reduce((nextBrief, label) => appendAssetMention(nextBrief, label), current));
        setSelectedNodeId(createdNodes[createdNodes.length - 1]?.id || "");
        setSeriesPlan(null);
        setFinalSubmission(null);
        await onComplete?.(createdNodes);
        onStatus?.({ kind: "ready", message: `${mentionLabels.length} 个媒体已上传到画布：${mentionLabels.map((label) => `@${label}`).join("、")}` });
      }
    } catch (error) {
      if (createdNodes.length) {
        await Promise.allSettled(createdNodes.map((node) => deleteCanvasNode(canvas.id, node.id)));
        await loadCanvas();
      }
      await onComplete?.();
      const partialMessage = uploadedAssets.length ? "。已上传的媒体会保留在资产库，可重新添加到画布" : "";
      onStatus?.({ kind: "failed", message: `${error?.message || "上传媒体到画布失败"}${partialMessage}` });
    } finally {
      setUploadingAssets(false);
    }
  }

  return { addAssetNode, assetUploadInputRef, createAssetReferenceNode, openCanvasAssetUpload, uploadCanvasAssets, uploadingAssets };
}
