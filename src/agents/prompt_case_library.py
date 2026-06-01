import asyncio
from copy import deepcopy
import logging
import threading
from pathlib import Path
import re
import time
from typing import Any

import httpx

from src.agents.quality_reference import QualityReference
from src.config import PROJECT_ROOT


UPSTREAM_REPO_URL = "https://github.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts"
UPSTREAM_RAW_BASE_URL = "https://raw.githubusercontent.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts/main"
UPSTREAM_README_URL = f"{UPSTREAM_RAW_BASE_URL}/README.md"
UPSTREAM_CASE_MARKDOWN_PATHS = (
    "cases/ecommerce.md",
    "cases/ad-creative.md",
    "cases/portrait.md",
    "cases/poster.md",
    "cases/character.md",
    "cases/ui.md",
    "cases/comparison.md",
)
CACHE_TTL_SECONDS = 3600
LOCAL_AWESOME_REPO = PROJECT_ROOT / "awesome-gpt-image-2-API-and-Prompts"
LOCAL_CASE_GLOBS = ("cases/*.md", "README*.md")
logger = logging.getLogger(__name__)


CURATED_FALLBACK_CASES: tuple[dict, ...] = (
    {
        "id": "portrait_neon_editorial",
        "profile": "portrait",
        "title": "Convenience Store Neon Portrait",
        "source_case": "README Case 1",
        "when_to_use": ["portrait", "editorial", "night", "neon", "35mm"],
        "pattern": "35mm film photography, mixed fluorescent and neon lighting, intimate medium shot, realistic skin texture, natural hair strands, authentic reflections, no watermark, no text",
        "prompt_excerpt": "35mm film photography portrait with neon and fluorescent lighting, intimate medium shot, realistic skin texture, layered reflections, authentic convenience store environment.",
        "takeaways": [
            "先定摄影媒介和镜头语言",
            "把光源关系写清楚",
            "把人物外观、姿态、材质和背景层次拆开写",
            "最后补负向约束",
        ],
    },
    {
        "id": "portrait_golden_hour_editorial",
        "profile": "portrait",
        "title": "Golden Hour Editorial Portrait",
        "source_case": "README portrait batch",
        "when_to_use": ["portrait", "golden hour", "editorial", "85mm", "cinematic"],
        "pattern": "golden hour sunlight, strong backlighting with lens flare, telephoto portrait look, rule-of-thirds composition, shallow depth of field, natural skin texture, warm nostalgic mood",
        "prompt_excerpt": "Golden hour editorial portrait, telephoto portrait lens look, warm nostalgic mood, shallow depth of field, natural skin texture and backlit atmosphere.",
        "takeaways": [
            "同时写光线、构图、镜头和情绪",
            "让人物仍然是主角，不被环境盖掉",
            "用少量风格关键词统一画面方向",
        ],
    },
    {
        "id": "poster_city_food_map",
        "profile": "poster",
        "title": "Chengdu Food Map Illustration",
        "source_case": "README Case 3",
        "when_to_use": ["poster", "map", "illustration", "hand-drawn", "infographic"],
        "pattern": "bird's-eye hand-drawn city map, multiple small themed illustrations, handwritten labels, decorative border, title placement, warm controlled palette, ratio specified",
        "prompt_excerpt": "Bird's-eye illustrated map poster with title, labels, decorative border, warm palette, multiple city landmarks and food icons in one coherent editorial layout.",
        "takeaways": [
            "先定义版式和视角",
            "明确标题、标注、图例等版面元素",
            "颜色体系和装饰边框要一起约束",
            "适合信息型海报而不是纯氛围图",
        ],
    },
    {
        "id": "poster_two_eras_cinematic",
        "profile": "poster",
        "title": "New York Across Two Centuries Poster",
        "source_case": "README Case 174",
        "when_to_use": ["poster", "cinematic", "city", "timeline", "epic"],
        "pattern": "single seamless poster image, one central figure, left/right era contrast without split-screen, coherent perspective, reflective pavement, atmospheric depth, no text",
        "prompt_excerpt": "Seamless cinematic city poster with one central subject, coherent perspective, strong atmosphere, reflective ground, era contrast without collage fragmentation.",
        "takeaways": [
            "复杂概念海报要先定主叙事结构",
            "多时空内容也要用统一透视和主体锚点收住",
            "避免把概念写成碎片化拼贴",
        ],
    },
    {
        "id": "product_watch_campaign",
        "profile": "product",
        "title": "Luxury Chronograph Watch Ad",
        "source_case": "README Case 144",
        "when_to_use": ["product", "luxury", "watch", "campaign", "studio"],
        "pattern": "single hero product, three-quarter angle, premium black studio, high-contrast specular highlights, controlled branding placement, reflective ground plane, restrained palette",
        "prompt_excerpt": "Luxury product campaign with one hero object, three-quarter angle, premium studio reflections, controlled branding, restrained palette and sharp material detail.",
        "takeaways": [
            "产品广告先锁单一 hero object",
            "材质、反光、摆位和背景光效要分层描述",
            "文字/logo/数字必须单独约束",
        ],
    },
    {
        "id": "product_miniature_diorama",
        "profile": "product",
        "title": "Miniature Diorama Skincare Advertisement",
        "source_case": "README Case 151",
        "when_to_use": ["product", "miniature", "diorama", "commercial", "storytelling"],
        "pattern": "oversized hero product, miniature workers as narrative accent, warm limited palette, studio diffused lighting, tilt-shift miniature look, commercial cleanliness",
        "prompt_excerpt": "Commercial miniature diorama around an oversized hero product, clean studio control, warm palette, story accents that still serve the main product.",
        "takeaways": [
            "夸张创意也要把主产品放在第一位",
            "附属元素只能服务主卖点，不能抢主体",
            "适合概念广告，不适合严肃 catalog 图",
        ],
    },
    {
        "id": "ui_neon_design_system",
        "profile": "ui",
        "title": "Cyberpunk Neon UI Design System",
        "source_case": "README Case 38",
        "when_to_use": ["ui", "dashboard", "design system", "cyberpunk", "neon"],
        "pattern": "design system request with web + mobile + cards + buttons + controls, strong theme source, explicit palette, layered lighting, high-tech surface detail",
        "prompt_excerpt": "High-fidelity interface design system prompt covering screens, cards, controls, palette, hierarchy, and visual language in one coherent delivery brief.",
        "takeaways": [
            "UI 类 prompt 要明确组件范围",
            "主题灵感、配色和信息层级一起给",
            "不要只写风格词，要写交付形态",
        ],
    },
    {
        "id": "ui_multi_panel_consistency",
        "profile": "ui",
        "title": "Multi-Panel Consistency Board",
        "source_case": "README Case 105",
        "when_to_use": ["ui", "board", "multi-panel", "consistency", "grid"],
        "pattern": "borderless grid, independent panels, strong subject consistency, consistent color and lighting, no text, no gap",
        "prompt_excerpt": "Grid-based multi-panel layout with strict consistency across panels, controlled spacing, stable lighting, and clear board structure.",
        "takeaways": [
            "多面板生成核心是角色和光线一致性",
            "先把 grid 结构写死",
            "减少多余文案，让版面先成立",
        ],
    },
    {
        "id": "storyboard_sitcom_production_board",
        "profile": "storyboard",
        "title": "Sitcom Production Board",
        "source_case": "Curated storyboard reference",
        "when_to_use": ["storyboard", "production board", "shot list", "sitcom", "visual planning"],
        "pattern": "16:9 film production board, shared creative direction bar, character model sheet, environment design, overhead movement map, numbered storyboard frames, shot size and movement labels, lighting mood notes, audio tone, cinematography notes, avoid repeated angles",
        "prompt_excerpt": "Grid-based cinematic production board for a short sitcom scene, with consistent characters, varied shot sizes, movement route, camera positions, lighting transitions, audio tone, and concise storyboard labels.",
        "takeaways": [
            "先把叙事拆成镜头目标",
            "每格都要改变景别、机位或动作重点",
            "制作板要同时覆盖角色、环境、动线、灯光和声音",
            "最终用结构化 JSON 控制版式和分区",
        ],
    },
    {
        "id": "character_anime_key_visual",
        "profile": "character",
        "title": "Mecha Girl Key Visual",
        "source_case": "README character batch",
        "when_to_use": ["character", "anime", "key visual", "concept art", "cinematic"],
        "pattern": "character identity first, silhouette gear details, environment lore second, low-key lighting, cinematic lens choice, controlled palette, editorial poster finish",
        "prompt_excerpt": "Anime character key visual with identity-first silhouette, costume and gear hierarchy, cinematic mood, controlled palette, and lore-supporting background.",
        "takeaways": [
            "角色设计先写身份和视觉锚点",
            "装备、发型、姿态、环境信息要分层",
            "用色彩系统把世界观收紧",
        ],
    },
    {
        "id": "default_cross_section_specimen",
        "profile": "default",
        "title": "Naturalist-Style Specimen Breakdown",
        "source_case": "README Case 68",
        "when_to_use": ["editorial", "diagram", "cutaway", "specimen", "structured"],
        "pattern": "hero object plus analytical breakdown, clear background control, annotation structure, dramatic but disciplined lighting, visual-first information hierarchy",
        "prompt_excerpt": "Structured editorial breakdown with one hero subject, analytical layout, controlled annotations, and a clear visual hierarchy.",
        "takeaways": [
            "结构化任务要先定义版式和信息层级",
            "复杂内容用模块化字段比长散文更稳",
            "让标题、标注和主体分工明确",
        ],
    },
)

SPECIALIZED_PROMPT_SKILL_CASES: tuple[dict, ...] = (
    {
        "id": "edit_preserve_subject_background_swap",
        "profile": "portrait",
        "title": "Subject-Preserving Background Edit",
        "source_case": "Industrial prompt skill edit policy",
        "when_to_use": ["edit", "background", "preserve", "source image", "背景", "保持", "人物不变"],
        "task_types": ["edit", "image_to_image"],
        "pattern": "use uploaded source image as identity anchor, preserve foreground subject, preserve pose and facial identity, change only requested background, match lighting perspective and edge integration, avoid full re-generation",
        "prompt_excerpt": "Edit the source image by changing only the requested background while preserving the foreground subject, identity, pose, proportions, and unedited regions; match lighting and perspective.",
        "takeaways": [
            "图像编辑必须先写 preserve，再写 modify",
            "背景替换不能重生成主体",
            "边缘、透视和光照要与源图匹配",
            "负向约束要禁止整图跑偏",
        ],
        "source": "curated_fallback",
        "source_path": "industrial/edit_policy",
    },
    {
        "id": "text_rendering_exact_typography",
        "profile": "poster",
        "title": "Exact Text Rendering Poster Policy",
        "source_case": "Industrial prompt skill typography policy",
        "when_to_use": ["text", "typography", "logo", "poster", "标题", "文字", "海报"],
        "task_types": ["text_rendering", "text_to_image"],
        "pattern": "quote every requested text literal exactly, specify placement, font style, baseline, kerning, readable typography, no extra text, no fake letters, no misspellings",
        "prompt_excerpt": "Render only the requested quoted text with exact spelling, clear readable typography, stable placement, and no invented extra text.",
        "takeaways": ["所有要求渲染的文字必须加引号", "文字位置、字体风格和可读性要明确", "禁止额外文案和伪文字"],
        "source": "curated_fallback",
        "source_path": "industrial/text_rendering_policy",
    },
    {
        "id": "character_locked_identity_sheet",
        "profile": "character",
        "title": "Locked Character Identity Anchors",
        "source_case": "Industrial prompt skill character policy",
        "when_to_use": ["character", "same person", "identity", "consistent", "角色一致", "同一个人"],
        "task_types": ["character_consistency", "text_to_image", "image_to_image"],
        "pattern": "lock identity anchors, hairstyle, face shape, outfit, accessories, age impression and proportions before changing scene, pose, expression or camera angle",
        "prompt_excerpt": "Keep a stable character identity sheet across images: face, hairstyle, outfit, accessories, body proportions, and age impression remain fixed while scene or pose changes.",
        "takeaways": ["先锁身份锚点再改场景", "发型、服装、配饰和比例必须持续一致", "多轮生成不能让年龄、脸型和服装漂移"],
        "source": "curated_fallback",
        "source_path": "industrial/character_policy",
    },
)


class PromptCaseLibrary:
    def __init__(self, local_root: str | Path | None = None):
        self.local_root = Path(local_root) if local_root is not None else LOCAL_AWESOME_REPO
        self._cache_lock = threading.RLock()
        self._async_locks: dict[int, asyncio.Lock] = {}
        self._cached_cases: list[dict] | None = None
        self._cached_at = 0.0

    async def get_cases(self) -> list[dict]:
        now = time.time()
        cached = self._cached_cases_copy(now)
        if cached is not None:
            return cached

        async with self._async_lock():
            now = time.time()
            cached = self._cached_cases_copy(now)
            if cached is not None:
                return cached

            local_cases = await asyncio.to_thread(self._load_local_cases)
            if local_cases:
                return self._cache_cases(_merge_local_cases(local_cases), now)

            try:
                markdown = await self._fetch_upstream_corpus()
                parsed = parse_upstream_markdown(markdown)
                if parsed:
                    return self._cache_cases(parsed, now)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                logger.warning("failed to load upstream prompt corpus; using curated fallback", exc_info=exc)

            return self._cache_cases(_fallback_cases(), now)

    def get_cases_sync(self) -> list[dict]:
        now = time.time()
        cached = self._cached_cases_copy(now)
        if cached is not None:
            return cached

        local_cases = self._load_local_cases()
        if local_cases:
            return self._cache_cases(_merge_local_cases(local_cases), now)
        return self._cache_cases(_fallback_cases(), now)

    def _async_lock(self) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        with self._cache_lock:
            lock = self._async_locks.get(loop_id)
            if lock is None:
                lock = asyncio.Lock()
                self._async_locks[loop_id] = lock
            return lock

    def _cached_cases_copy(self, now: float) -> list[dict] | None:
        with self._cache_lock:
            if self._cached_cases and now - self._cached_at < CACHE_TTL_SECONDS:
                return deepcopy(self._cached_cases)
        return None

    def _cache_cases(self, cases: list[dict], cached_at: float) -> list[dict]:
        with self._cache_lock:
            self._cached_cases = cases
            self._cached_at = cached_at
            return deepcopy(cases)

    def _load_local_cases(self) -> list[dict]:
        if not self.local_root.exists():
            return []

        markdown_parts: list[tuple[Path, str]] = []
        for pattern in LOCAL_CASE_GLOBS:
            for path in sorted(self.local_root.glob(pattern)):
                if path.is_file():
                    try:
                        markdown_parts.append((path, path.read_text(encoding="utf-8")))
                    except UnicodeDecodeError:
                        logger.warning("failed to decode local prompt case file: %s", path)

        cases: list[dict] = []
        for path, markdown in markdown_parts:
            parsed = parse_upstream_markdown(markdown)
            if not parsed:
                continue
            for case in parsed:
                enriched = _with_default_case_metadata(case, source="local_awesome_cases")
                cases.append(enriched)
        return _dedupe_cases(cases)

    async def _fetch_upstream_corpus(self) -> str:
        timeout = httpx.Timeout(45.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            urls = [f"{UPSTREAM_RAW_BASE_URL}/{path}" for path in UPSTREAM_CASE_MARKDOWN_PATHS]
            responses = await asyncio.gather(*(self._fetch_markdown(client, url) for url in urls), return_exceptions=True)
            markdowns: list[str | None] = [response if isinstance(response, str) and response.strip() else None for response in responses]
            for index, markdown in enumerate(markdowns):
                if markdown is None:
                    try:
                        markdowns[index] = await self._fetch_markdown(client, urls[index])
                    except httpx.HTTPError as exc:
                        logger.warning("failed to retry upstream prompt case file: %s", urls[index], exc_info=exc)
            complete_markdowns = [markdown for markdown in markdowns if isinstance(markdown, str) and markdown.strip()]
            if complete_markdowns:
                return "\n\n".join(complete_markdowns)
            return await self._fetch_markdown(client, UPSTREAM_README_URL)

    @staticmethod
    async def _fetch_markdown(client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url, headers={"Accept": "text/plain"})
        response.raise_for_status()
        return response.text


prompt_case_library = PromptCaseLibrary()


async def retrieve_prompt_cases(prompt: str, limit: int = 5, task_type: str | None = None) -> list[dict]:
    return _select_prompt_cases(await prompt_case_library.get_cases(), prompt, limit, task_type)


def retrieve_prompt_cases_sync(prompt: str, limit: int = 5, task_type: str | None = None) -> list[dict]:
    return _select_prompt_cases(prompt_case_library.get_cases_sync(), prompt, limit, task_type)


def _select_prompt_cases(cases: list[dict], prompt: str, limit: int, task_type: str | None) -> list[dict]:
    profile = _profile_for_task(prompt, task_type)
    normalized = f"{prompt} {task_type or ''}".lower()

    def score(case: dict) -> tuple[int, int, int]:
        keyword_hits = sum(1 for item in case.get("when_to_use", []) if item.lower() in normalized)
        prompt_hits = sum(1 for item in _split_tokens(case.get("pattern", "")) if item in normalized)
        task_hits = sum(1 for item in case.get("task_types", []) if str(item).lower() in normalized)
        profile_bonus = 100 if case.get("profile") == profile else 0
        default_bonus = 10 if case.get("profile") == "default" else 0
        edit_bonus = 130 if task_type in {"edit", "inpaint", "outpaint", "style_transfer"} and _case_supports_edit(case) else 0
        return (profile_bonus + default_bonus + edit_bonus + task_hits * 12 + keyword_hits * 6 + min(prompt_hits, 12), keyword_hits, prompt_hits)

    ranked = sorted(cases, key=score, reverse=True)
    selected: list[dict] = []
    for case in ranked:
        if case.get("profile") == profile or _case_supports_task(case, task_type) or (case.get("profile") == "default" and len(selected) < limit):
            selected.append(case)
        if len(selected) >= limit:
            break
    return selected


def parse_upstream_markdown(markdown: str) -> list[dict]:
    normalized_markdown = markdown.lower()
    if not any(
        marker in normalized_markdown
        for marker in (
            "awesome-gpt-image-2-api-and-prompts",
            "awesome gpt image 2 api and prompts",
            "awesome-gpt-image-2-prompts",
        )
    ):
        return []

    sections = _profiled_sections(markdown)
    cases: list[dict] = []

    for section_start, section_end, section_title, profile in sections:
        section_body = markdown[section_start:section_end]

        case_pattern = re.compile(r"^###\s+Case\s+(\d+):\s+(.+?)\n", re.MULTILINE)
        case_matches = list(case_pattern.finditer(section_body))
        for case_index, case_match in enumerate(case_matches):
            case_number = case_match.group(1).strip()
            case_title = _sanitize_case_title(_clean_case_title(case_match.group(2))) or f"Case {case_number}"
            case_start = case_match.end()
            case_end = case_matches[case_index + 1].start() if case_index + 1 < len(case_matches) else len(section_body)
            case_body = section_body[case_start:case_end]
            prompt_text = _sanitize_prompt_text(_extract_prompt_text(case_body))
            if not prompt_text:
                continue

            source_case = f"{section_title} / Case {case_number}"
            cases.append(
                {
                    "id": f"{profile}_{case_number}",
                    "profile": profile,
                    "title": case_title,
                    "source_case": source_case,
                    "when_to_use": _keywords_from_text(section_title, case_title),
                    "pattern": _compress_prompt_pattern(prompt_text),
                    "prompt_excerpt": _trim_text(prompt_text, 560),
                    "visual_dna": _extract_visual_dna(profile, prompt_text),
                    "prompt_spec": _case_prompt_spec(profile, prompt_text),
                    "takeaways": _derive_takeaways(profile, prompt_text),
                    "repo_url": UPSTREAM_REPO_URL,
                }
            )

    return cases


def _profiled_sections(markdown: str) -> list[tuple[int, int, str, str]]:
    headings: list[tuple[int, int, str, str]] = []
    in_fence = False
    position = 0
    for line in markdown.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence:
            match = re.match(r"^(#{1,2})\s+(.+?)\s*$", line)
            if match:
                section_title = match.group(2).strip()
                profile = _profile_from_section(section_title)
                if profile is not None:
                    headings.append((position, position + len(line), section_title, profile))
        position += len(line)

    return [
        (heading_end, headings[index + 1][0] if index + 1 < len(headings) else len(markdown), section_title, profile)
        for index, (_, heading_end, section_title, profile) in enumerate(headings)
    ]


def _profile_from_section(section_title: str) -> str | None:
    normalized = section_title.lower()
    if "portrait" in normalized or "photography" in normalized:
        return "portrait"
    if "poster" in normalized or "illustration" in normalized or "ad creative" in normalized:
        return "poster"
    if "character" in normalized:
        return "character"
    if "ui" in normalized or "social media" in normalized or "mockup" in normalized:
        return "ui"
    if "e-commerce" in normalized or "ecommerce" in normalized or "advert" in normalized or "product" in normalized or "commercial" in normalized:
        return "product"
    if "comparison" in normalized or "misc" in normalized or "special" in normalized or "community" in normalized:
        return "default"
    return None


def _clean_case_title(raw_title: str) -> str:
    without_author = re.sub(r"\s+\(by\s+.+?\)\s*$", "", raw_title.strip())
    link_match = re.search(r"\[([^\]]+)\]\([^)]+\)", without_author)
    return link_match.group(1).strip() if link_match else without_author


def _sanitize_case_title(title: str) -> str:
    return _trim_text(_sanitize_case_segment(title), 120)


def _extract_prompt_text(case_body: str) -> str:
    prompt_match = re.search(r"(?i)(?:\*\*\s*prompt\s*\*\*|\bprompt\b)\s*:", case_body)
    if not prompt_match:
        return _extract_first_fenced_prompt(case_body)
    prompt_body = case_body[prompt_match.end() :]

    fenced_match = re.search(r"```(?:[\w-]+)?\n(.*?)```", prompt_body, re.DOTALL)
    if fenced_match:
        return _cleanup_prompt_text(fenced_match.group(1))

    inline_match = re.search(r"`([^`]{40,})`", prompt_body, re.DOTALL)
    if inline_match:
        return _cleanup_prompt_text(inline_match.group(1))

    paragraph_match = re.search(r"\n\s*\n(.*?)(?:\n\s*\n|\Z)", prompt_body, re.DOTALL)
    if paragraph_match:
        return _cleanup_prompt_text(paragraph_match.group(1))

    return _cleanup_prompt_text(prompt_body)


def _extract_first_fenced_prompt(case_body: str) -> str:
    for match in re.finditer(r"```(?:[\w-]+)?\n(.*?)```", case_body, re.DOTALL):
        candidate = _cleanup_prompt_text(match.group(1))
        if len(candidate) >= 40 and not _looks_like_code(candidate):
            return candidate
    return ""


def _looks_like_code(text: str) -> bool:
    normalized = text.lstrip().lower()
    return normalized.startswith(("curl ", "import ", "const ", "python ", "npm ", "{"))


def _cleanup_prompt_text(text: str) -> str:
    cleaned = text.replace("\r", "\n")
    cleaned = re.sub(r"^\s*>?\s?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    cleaned = " ".join(part.strip() for part in cleaned.splitlines() if part.strip())
    return cleaned.strip("` ").strip()


def _compress_prompt_pattern(prompt_text: str) -> str:
    segments = [segment.strip() for segment in re.split(r"[,\n]", prompt_text) if segment.strip()]
    if len(segments) <= 10:
        return ", ".join(segments)

    leading = segments[:7]
    trailing = [segment for segment in segments[-4:] if "avoid" in segment.lower() or "negative" in segment.lower() or "no " in segment.lower()]
    merged = leading + trailing
    deduped: list[str] = []
    for segment in merged:
        if segment not in deduped:
            deduped.append(segment)
    return ", ".join(deduped[:12])


def _extract_visual_dna(profile: str, prompt_text: str) -> dict[str, list[str]]:
    segments = _prompt_segments(prompt_text)
    return {
        "composition": _select_segments(segments, _COMPOSITION_TERMS, fallback_count=2),
        "subject_strategy": _select_segments(segments, _SUBJECT_TERMS, fallback_count=2),
        "lighting": _select_segments(segments, _LIGHTING_TERMS, fallback_count=0),
        "camera": _select_segments(segments, _CAMERA_TERMS, fallback_count=0),
        "materials": _select_segments(segments, _MATERIAL_TERMS, fallback_count=0),
        "typography": _select_segments(segments, _TEXT_TERMS, fallback_count=0),
        "negative_patterns": _select_segments(segments, _NEGATIVE_TERMS, fallback_count=0),
        "profile_strategy": [_profile_strategy(profile)],
    }


def _case_prompt_spec(profile: str, prompt_text: str) -> dict[str, Any]:
    visual_dna = _extract_visual_dna(profile, prompt_text)
    return {
        "profile": profile,
        "creative_strategy": _profile_strategy(profile),
        "scene_graph": {
            "hero_subject": _first_non_empty(visual_dna["subject_strategy"], _trim_text(prompt_text, 180)),
            "environment": _first_non_empty(visual_dna["composition"], "controlled environment derived from the source case"),
        },
        "composition": {
            "layout": _first_non_empty(visual_dna["composition"], "clear focal hierarchy"),
            "camera": _first_non_empty(visual_dna["camera"], "viewpoint chosen to serve the subject"),
        },
        "style_system": {
            "lighting": _first_non_empty(visual_dna["lighting"], "controlled professional lighting"),
            "materials": visual_dna["materials"],
        },
        "text_system": {
            "typography": visual_dna["typography"],
        },
        "constraints": {
            "avoid": visual_dna["negative_patterns"],
        },
    }


def _sanitize_prompt_text(prompt_text: str) -> str:
    return ", ".join(_prompt_segments(prompt_text))


def _prompt_segments(prompt_text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", prompt_text).strip()
    segments: list[str] = []
    for raw_segment in re.split(r"[,，。;；\n]", normalized):
        segment = _sanitize_case_segment(raw_segment.strip(" ;.。"))
        if segment and segment not in segments:
            segments.append(segment)
    return segments


def _sanitize_case_segment(segment: str) -> str:
    compact = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", segment)
    compact = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", compact)
    compact = re.sub(r"https?://\S+|www\.\S+", "", compact)
    compact = re.sub(r"<[^>]*>", "", compact)
    compact = re.sub(r"[<>{}]", "", compact)
    compact = re.sub(r"\s+", " ", compact).strip(" `\t")
    if not compact:
        return ""
    normalized = compact.lower()
    if any(phrase in normalized for phrase in _CASE_INJECTION_PHRASES):
        return ""
    return _trim_text(compact, _MAX_CASE_SEGMENT_CHARS)


def _select_segments(segments: list[str], terms: tuple[str, ...], *, fallback_count: int) -> list[str]:
    selected: list[str] = []
    for segment in segments:
        normalized = segment.lower()
        if any(term in normalized for term in terms) and segment not in selected:
            selected.append(segment)
        if len(selected) >= 4:
            break
    if selected or fallback_count <= 0:
        return selected
    return segments[:fallback_count]


def _first_non_empty(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def _profile_strategy(profile: str) -> str:
    return {
        "portrait": "identity-first portrait strategy with lens, light, skin texture, and emotional atmosphere separated",
        "poster": "layout-first poster strategy with subject hierarchy, negative space, typography, and narrative flow separated",
        "product": "commercial hero-product strategy with product angle, materials, reflections, brand text, and controlled studio lighting separated",
        "ui": "interface-delivery strategy with device frame, components, information hierarchy, platform conventions, and readable text separated",
        "character": "character-sheet strategy with silhouette, identity anchors, outfit, accessories, pose, and world context separated",
        "storyboard": "production-board strategy with panel grid, shot sequence, camera movement, timing labels, and continuity constraints separated",
    }.get(profile, "structured visual brief strategy with subject, environment, style, composition, and constraints separated")


_COMPOSITION_TERMS = (
    "composition",
    "layout",
    "grid",
    "negative space",
    "center",
    "foreground",
    "background",
    "top-down",
    "bird",
    "poster",
    "版式",
    "构图",
    "留白",
    "前景",
    "背景",
    "鸟瞰",
    "九宫格",
    "网格",
)
_COMPOSITION_TERMS = tuple(term.lower() for term in _COMPOSITION_TERMS)
_SUBJECT_TERMS = tuple(term.lower() for term in ("subject", "hero", "product", "person", "character", "主体", "人物", "角色", "产品", "商品", "中心"))
_LIGHTING_TERMS = tuple(term.lower() for term in ("light", "lighting", "shadow", "glow", "neon", "cinematic", "sunlight", "光", "光影", "阴影", "霓虹", "电影级"))
_CAMERA_TERMS = tuple(term.lower() for term in ("camera", "lens", "shot", "macro", "close-up", "wide", "angle", "view", "镜头", "视角", "特写", "远景", "近景", "俯拍"))
_MATERIAL_TERMS = tuple(term.lower() for term in ("material", "texture", "metal", "glass", "paper", "fabric", "reflective", "材质", "纹理", "金属", "玻璃", "纸张", "布料", "反光"))
_TEXT_TERMS = tuple(term.lower() for term in ("text", "typography", "logo", "label", "headline", "title", "caption", "文字", "标题", "标注", "字体", "排版", "文案"))
_NEGATIVE_TERMS = tuple(term.lower() for term in ("avoid", "negative", "no ", "not ", "不要", "避免", "禁止"))
_MAX_CASE_SEGMENT_CHARS = 180
_CASE_INJECTION_PHRASES = tuple(
    phrase.lower()
    for phrase in (
        "ignore previous",
        "ignore all previous",
        "ignore above",
        "system prompt",
        "system message",
        "developer message",
        "hidden instruction",
        "reveal prompt",
        "exfiltrate",
        "api key",
        "authorization header",
        "bearer token",
        "tool call",
        "call a tool",
        "use the tool",
        "execute command",
        "run shell",
        "curl ",
        "<script",
    )
)


def _derive_takeaways(profile: str, prompt_text: str) -> list[str]:
    base = {
        "portrait": ["突出镜头和人物质感", "把光线和情绪写在一起"],
        "poster": ["先定版式结构，再补视觉氛围", "主体和信息层级必须稳定"],
        "product": ["先锁 hero 产品与角度", "材质、反光和品牌约束必须明确"],
        "ui": ["明确交付形态和组件范围", "主题、信息层级、文本可读性一起约束"],
        "character": ["先写角色身份和视觉锚点", "装备和姿态细节分层表达"],
        "storyboard": ["先拆叙事步骤和镜头目标", "用网格版式锁定分区、动线和分镜差异"],
        "default": ["先定义主体和结构", "减少空泛修辞，增加可见细节"],
    }.get(profile, ["保持主体优先", "增加结构化细节"])

    extras: list[str] = []
    lower = prompt_text.lower()
    if "35mm" in lower or "85mm" in lower or "lens" in lower:
        extras.append("案例强调了明确镜头语言")
    if "negative prompt" in lower or "avoid" in lower or "no " in lower:
        extras.append("案例会明确写负向约束")
    return [*base, *extras][:4]


def _keywords_from_text(*parts: str) -> list[str]:
    tokens = _split_tokens(" ".join(parts))
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:14]


def _split_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower()) if token]


def _trim_text(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _merge_local_cases(local_cases: list[dict]) -> list[dict]:
    return _dedupe_cases([*local_cases, *[_with_default_case_metadata(case, source="curated_fallback") for case in SPECIALIZED_PROMPT_SKILL_CASES]])


def _fallback_cases() -> list[dict]:
    return [_with_default_case_metadata(case, source="curated_fallback") for case in (*SPECIALIZED_PROMPT_SKILL_CASES, *CURATED_FALLBACK_CASES)]


def _with_default_case_metadata(case: dict, *, source: str) -> dict:
    enriched = dict(case)
    title = _sanitize_case_title(str(enriched.get("title") or ""))
    if title:
        enriched["title"] = title
    else:
        enriched.pop("title", None)
    profile = str(enriched.get("profile") or "default")
    case_prompt = _sanitize_prompt_text(str(enriched.get("pattern") or enriched.get("prompt_excerpt") or ""))
    if case_prompt:
        enriched.setdefault("visual_dna", _extract_visual_dna(profile, case_prompt))
        enriched.setdefault("prompt_spec", _case_prompt_spec(profile, case_prompt))
    enriched.pop("source_path", None)
    enriched.pop("source_url", None)
    enriched.setdefault("source", source)
    enriched.setdefault("task_types", _task_types_for_case(enriched))
    enriched.setdefault("tags", enriched.get("when_to_use", []))
    enriched.setdefault("aesthetic_score", None)
    return enriched


def _dedupe_cases(cases: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        key = (str(case.get("id", "")), str(case.get("title", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    return deduped


def _task_types_for_case(case: dict) -> list[str]:
    text = " ".join(str(value) for value in (case.get("profile"), case.get("title"), case.get("pattern"), case.get("prompt_excerpt"))).lower()
    task_types = ["text_to_image"]
    if any(token in text for token in ("preserve", "保持", "replace", "edit", "background", "背景", "mask")):
        task_types.extend(["edit", "image_to_image"])
    if any(token in text for token in ("typography", "text", "logo", "label", "文字", "标题")):
        task_types.append("text_rendering")
    if any(token in text for token in ("character", "角色", "consistent", "identity")):
        task_types.append("character_consistency")
    return list(dict.fromkeys(task_types))


def _profile_for_task(prompt: str, task_type: str | None) -> str:
    if task_type == "character_consistency":
        return "character"
    return QualityReference.select_profile(prompt)


def _case_supports_task(case: dict, task_type: str | None) -> bool:
    if task_type is None:
        return False
    return task_type in case.get("task_types", []) or (task_type == "character_consistency" and case.get("profile") == "character")


def _case_supports_edit(case: dict) -> bool:
    return "edit" in case.get("task_types", []) or "image_to_image" in case.get("task_types", [])
