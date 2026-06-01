const SAFE_DATA_IMAGE_PATTERN = /^data:image\/(png|jpe?g|webp);base64,[a-z0-9+/=\s]+$/i;
const SAFE_UPLOAD_FILENAME_PATTERN = /^[\w-]+\.(png|jpe?g|webp|mp4|webm|mov)$/i;
const SAFE_UPLOAD_PREFIX = "/uploads/image-optimizer/";

export function safeDisplayUrl(url) {
  if (typeof url !== "string" || !url.trim() || url.startsWith("mock://")) {
    return "";
  }
  if (SAFE_DATA_IMAGE_PATTERN.test(url)) {
    return url;
  }
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin === window.location.origin) {
      if (!parsed.pathname.startsWith(SAFE_UPLOAD_PREFIX)) {
        return "";
      }
      const filename = parsed.pathname.slice(SAFE_UPLOAD_PREFIX.length);
      return SAFE_UPLOAD_FILENAME_PATTERN.test(filename) ? parsed.href : "";
    }
    return "";
  } catch {
    return "";
  }
}

export function isImageAsset(asset) {
  return asset?.kind === "image" || String(asset?.media_type || "").startsWith("image/");
}

export function isVideoAsset(asset) {
  return asset?.kind === "video" || String(asset?.media_type || "").startsWith("video/");
}

export function assetKindLabel(asset) {
  if (isImageAsset(asset)) {
    return "图片";
  }
  if (isVideoAsset(asset)) {
    return "视频";
  }
  return "媒体";
}

export function assetLabel(asset, fallback = "资产") {
  return asset?.metadata?.filename || asset?.metadata?.stored_filename || `${fallback} ${asset?.id?.slice?.(0, 8) || ""}`.trim();
}
