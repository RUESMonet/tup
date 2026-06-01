import { useEffect, useRef, useState } from "react";

import { fetchModels, isAbortError, requestErrorMessage } from "../api";
import { fallbackModels } from "../constants";

export function useImageModels({ onStatus }) {
  const [models, setModels] = useState(fallbackModels);
  const [model, setModel] = useState("openai");
  const [modelsLoading, setModelsLoading] = useState(false);
  const loadingRef = useRef(false);
  const requestRef = useRef(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  async function loadModels() {
    if (loadingRef.current) {
      return;
    }

    loadingRef.current = true;
    setModelsLoading(true);
    const controller = new AbortController();
    requestRef.current = controller;

    try {
      const payload = await fetchModels({ signal: controller.signal });
      const available = payload.models?.length ? payload.models : fallbackModels;
      setModels(available);
      setModel((current) => (available.some((item) => item.id === current) ? current : available[0]?.id || current));
    } catch (error) {
      if (!isAbortError(error)) {
        setModels(fallbackModels);
        onStatus({ kind: "failed", message: requestErrorMessage(error, "模型列表不可用，已使用默认模型") });
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        loadingRef.current = false;
        setModelsLoading(false);
      }
    }
  }

  return { models, model, setModel, loadModels, modelsLoading };
}
