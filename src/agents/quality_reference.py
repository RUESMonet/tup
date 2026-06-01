from copy import deepcopy
import re


class QualityReference:
    SOURCE_NAME = "EvoLinkAI/awesome-gpt-image-2-prompts"
    SOURCE_URL = "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts"
    PROFILE_PRIORITY = ("storyboard", "product", "portrait", "character", "ui", "poster")

    PROFILES: dict[str, dict[str, tuple[str, ...] | str]] = {
        "storyboard": {
            "keywords": (
                "漫剧",
                "短剧",
                "情景喜剧",
                "故事板",
                "分镜",
                "制作板",
                "电影制作板",
                "视觉规划表",
                "镜头表",
                "预制作",
                "导演板",
                "storyboard",
                "production board",
                "visual planning",
                "shot list",
                "sitcom",
            ),
            "style": "cinematic pre-production board, clean grid-based storyboard sheet, professional director visual guide",
            "lighting": "controlled natural light progression, readable character lighting, clear mood transitions across panels",
            "camera": "16:9 production board layout, varied shot sizes, labeled camera positions, clear storyboard progression",
            "atmosphere": "coherent cinematic planning sheet with character consistency, scene continuity, and readable visual rhythm",
            "constraints": "keep shot-to-shot identity consistent, avoid repeated identical angles, preserve the source story beats",
        },
        "portrait": {
            "keywords": ("人像", "肖像", "人物", "女孩", "男孩", "portrait", "person", "cosplayer"),
            "style": "cinematic editorial portrait, 35mm film photography, natural skin texture",
            "lighting": "soft rim light, balanced highlight rolloff, subtle shadow contrast",
            "camera": "intimate medium shot, 85mm portrait lens, shallow depth of field",
            "atmosphere": "realistic fabric detail, natural hair strands, refined color grading",
            "constraints": "preserve natural facial proportions and believable skin texture",
        },
        "poster": {
            "keywords": ("海报", "插画", "城市", "poster", "illustration", "map", "travel"),
            "style": "contemporary poster design, refined editorial illustration, textured print finish",
            "lighting": "clear key light, layered atmospheric depth, controlled contrast",
            "camera": "strong focal hierarchy, dynamic composition, generous negative space",
            "atmosphere": "visually powerful but uncluttered, crisp typography-safe layout",
            "constraints": "keep layout readable and avoid overcrowded decorative elements",
        },
        "character": {
            "keywords": ("角色", "设定", "动漫", "二次元", "character", "anime", "chibi", "reference sheet"),
            "style": "official character reference sheet, clean anime rendering, coherent costume design",
            "lighting": "soft studio lighting, clean cel shading, readable material highlights",
            "camera": "front-facing character view, balanced turnaround layout, full-body framing",
            "atmosphere": "consistent silhouette, clear accessories, production-ready concept art",
            "constraints": "keep identity, outfit details, and proportions consistent",
        },
        "ui": {
            "keywords": ("界面", "ui", "app", "原型", "社媒", "截图", "mockup", "feed", "dashboard"),
            "style": "high-fidelity product UI mockup, realistic screen capture, polished visual system",
            "lighting": "even screen illumination, clean contrast, subtle device reflections",
            "camera": "straight-on readable composition, precise spacing, aligned grid structure",
            "atmosphere": "credible application state, legible hierarchy, production-quality interface",
            "constraints": "avoid garbled text, broken alignment, and decorative clutter",
        },
        "product": {
            "keywords": ("产品", "广告", "静物", "包装", "手机", "iphone", "i phone", "phone", "product", "ad", "commercial", "shelf"),
            "style": "realistic commercial product photography, premium material rendering",
            "lighting": "softbox studio lighting, controlled reflections, clean specular highlights",
            "camera": "three-quarter product angle, centered hero composition, sharp foreground detail",
            "atmosphere": "credible scale, tactile surfaces, advertising-grade finish",
            "constraints": "avoid warped labels, incorrect counts, and inconsistent object geometry",
        },
        "default": {
            "keywords": (),
            "style": "cinematic photorealistic style, high-detail visual direction",
            "lighting": "soft directional light, balanced contrast, detailed shadows",
            "camera": "35mm lens, clear composition, depth of field",
            "atmosphere": "polished, coherent, high detail, strong subject readability",
            "constraints": "preserve the user's core subject and remove visual ambiguity",
        },
    }

    QUALITY_RUBRIC: tuple[dict[str, str], ...] = (
        {"dimension": "subject", "criterion": "core subject is explicit, specific, and easy to verify"},
        {"dimension": "style", "criterion": "visual style or medium is intentionally specified"},
        {"dimension": "lighting", "criterion": "lighting, mood, or atmosphere guides the image"},
        {"dimension": "composition", "criterion": "camera, framing, layout, or focal hierarchy is clear"},
        {"dimension": "detail", "criterion": "material, texture, identity, or scene details are concrete"},
        {"dimension": "constraints", "criterion": "negative constraints reduce artifacts and ambiguity"},
        {"dimension": "coherence", "criterion": "all instructions preserve one consistent intent"},
    )

    HIGH_QUALITY_MARKERS: dict[str, tuple[str, ...]] = {
        "style": (
            "photorealistic",
            "cinematic",
            "editorial",
            "illustration",
            "anime",
            "mockup",
            "concept art",
            "写实",
            "电影感",
            "插画",
            "动漫",
            "电影",
            "情景喜剧",
            "制作板",
        ),
        "lighting": (
            "light",
            "lighting",
            "shadow",
            "rim light",
            "softbox",
            "contrast",
            "氛围",
            "光",
            "光线",
            "阴影",
            "柔光",
            "霓虹",
            "灯光",
            "自然光",
        ),
        "composition": (
            "lens",
            "camera",
            "composition",
            "framing",
            "focal",
            "depth of field",
            "negative space",
            "构图",
            "镜头",
            "景深",
            "焦点",
            "景别",
            "机位",
            "远景",
            "中景",
            "全景",
            "微距",
            "16:9",
            "比例",
            "storyboard",
            "shot",
            "grid",
            "分镜",
        ),
        "detail": (
            "texture",
            "material",
            "detail",
            "high-fidelity",
            "production-ready",
            "polished",
            "材质",
            "纹理",
            "细节",
            "高质量",
            "角色",
            "服装",
            "配饰",
            "道具",
            "环境",
            "场景",
            "调色板",
            "音频",
        ),
        "constraints": (
            "negative prompt",
            "avoid",
            "without",
            "preserve",
            "consistent",
            "不要",
            "避免",
            "保持",
            "一致",
        ),
    }
    OPTIMIZATION_HINTS: dict[str, str] = {
        "subject": "补充主体身份、数量、关键外观、动作和场景关系，避免只写泛泛对象。",
        "style": "指定明确媒介或风格方向，例如写实摄影、海报插画、角色设定、产品广告或 UI mockup。",
        "lighting": "补充主光、辅光、氛围光、阴影或时间段，让模型稳定控制画面情绪。",
        "composition": "补充镜头、景别、构图、焦点层级或留白要求，减少随机构图。",
        "detail": "补充材质、纹理、服装、环境、品牌感或可验证细节，提高成片质感。",
        "constraints": "加入负向词和一致性约束，限制模糊、畸形、文字错误、水印、布局混乱等问题。",
        "coherence": "保持所有优化都围绕原始主体，不新增会改变用户意图的对象或风格。",
    }

    @classmethod
    def select_profile(cls, prompt: str) -> str:
        normalized = prompt.lower()
        for profile in cls.PROFILE_PRIORITY:
            terms = cls.PROFILES[profile]
            keywords = terms["keywords"]
            if isinstance(keywords, tuple) and any(cls._keyword_matches(normalized, keyword.lower()) for keyword in keywords):
                return profile
        return "default"

    @classmethod
    def profile_terms(cls, prompt: str) -> dict[str, tuple[str, ...] | str]:
        return cls.PROFILES[cls.select_profile(prompt)]

    @staticmethod
    def _keyword_matches(normalized_prompt: str, keyword: str) -> bool:
        if keyword.isascii():
            return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", normalized_prompt) is not None
        return keyword in normalized_prompt

    @classmethod
    def prompt_quality(cls, prompt: str) -> dict:
        normalized = prompt.lower()
        matched_dimensions = [
            dimension
            for dimension, markers in cls.HIGH_QUALITY_MARKERS.items()
            if any(marker.lower() in normalized for marker in markers)
        ]
        missing_dimensions = [
            item["dimension"]
            for item in cls.QUALITY_RUBRIC
            if item["dimension"] != "coherence" and item["dimension"] not in matched_dimensions
        ]
        if len(prompt.strip()) >= 8:
            matched_dimensions.insert(0, "subject")
            if "subject" in missing_dimensions:
                missing_dimensions.remove("subject")

        return {
            "source": cls.SOURCE_NAME,
            "source_url": cls.SOURCE_URL,
            "profile": cls.select_profile(prompt),
            "matched_dimensions": matched_dimensions,
            "missing_dimensions": missing_dimensions,
            "optimization_hints": cls.optimization_hints(prompt),
            "rubric": cls.QUALITY_RUBRIC,
        }

    @classmethod
    def scoring_reference(cls, prompt: str) -> dict:
        profile = cls.select_profile(prompt)
        terms = cls.PROFILES[profile]
        return {
            "source": cls.SOURCE_NAME,
            "source_url": cls.SOURCE_URL,
            "profile": profile,
            "rubric": cls.QUALITY_RUBRIC,
            "profile_reference": {
                "style": terms["style"],
                "lighting": terms["lighting"],
                "camera_and_composition": terms["camera"],
                "atmosphere": terms["atmosphere"],
                "constraints": terms["constraints"],
            },
        }

    @classmethod
    def optimization_hints(cls, prompt: str, defects: list[str] | None = None) -> list[str]:
        quality = cls._prompt_quality_without_hints(prompt)
        missing = quality["missing_dimensions"]
        hints = [cls.OPTIMIZATION_HINTS[dimension] for dimension in missing if dimension in cls.OPTIMIZATION_HINTS]
        normalized = prompt.lower()

        if "[" in prompt and "]" in prompt:
            hints.insert(0, "去掉方括号占位符，把括号内内容作为真实主体、名称或文字要求处理，避免模型把括号也画出来。")
        if cls._mentions_text_or_logo(prompt):
            hints.append("把原文要求的 logo、名称、标签或文字作为独立约束：清晰可读、不生成乱码、不添加原文没有的品牌文字。")
        profile = cls.select_profile(prompt)
        if profile == "storyboard":
            hints.append("按漫剧/分镜制作板处理：把叙事步骤拆成镜头目标，再合并为 16:9 网格化视觉规划板 JSON。")
            hints.append("为每个故事板帧明确景别、机位、运动、动作情绪和差异化场景重点，避免连续帧重复同一沙发角度。")
        if profile == "product":
            hints.append("按产品图处理：锁定原文里的主视觉产品、数量、材质和场景层级，不新增原文没有的道具、地点或品牌。")
        if "negative prompt" not in normalized and "避免" not in prompt and "不要" not in prompt:
            negatives = ["低清", "模糊", "水印", "主体漂移", "布局拥挤"]
            if cls._mentions_text_or_logo(prompt):
                negatives.extend(["文字乱码", "logo 变形"])
            if cls._mentions_any(normalized, ("iphone", "i phone", "phone")) or "手机" in prompt:
                negatives.extend(["手机变形", "重复手机"])
            hints.append(f"补充负向词：避免{'、'.join(dict.fromkeys(negatives))}。")
        if len(prompt) > 180:
            hints.append("把长段落拆成 subject / environment / lighting / camera / color / constraints，减少模型把细节混在一起。")

        defect_text = " ".join(defects or [])
        if "主体" in defect_text or "subject" in defect_text:
            hints.append("强化主体锚点：把主体放在 prompt 开头，并要求画面中清晰可辨。")
        if "构图" in defect_text or "composition" in defect_text:
            hints.append("针对构图缺陷加入镜头、景别、焦点层级和画面留白要求。")
        if "模糊" in defect_text or "blurry" in defect_text:
            hints.append("加入清晰度和细节要求，并把 blurry、low resolution 放入负向词。")
        if "风格" in defect_text or "style" in defect_text:
            hints.append("收窄风格范围，避免多个互相冲突的艺术方向同时出现。")

        if not hints:
            hints.append("当前 prompt 已覆盖主要质量维度；优化重点是保持原意、明确主体层级，并减少不必要的新增元素。")
        return list(dict.fromkeys(hints))

    @classmethod
    def optimized_prompt_payload(cls, prompt: str, hints: list[str] | None = None) -> dict:
        clean_prompt = " ".join(prompt.strip().split())
        profile = cls.select_profile(clean_prompt)
        terms = cls.PROFILES[profile]
        faithful_prompt = cls._strip_placeholders(clean_prompt)

        return {
            "task": "image_generation",
            "source": "quality_reference_optimizer",
            "original_prompt": clean_prompt,
            "profile": profile,
            "optimization_hints": hints or cls.optimization_hints(clean_prompt),
            "prompt": {
                "subject": faithful_prompt,
                "environment": cls._environment_instruction(faithful_prompt),
                "style": terms["style"],
                "lighting": terms["lighting"],
                "camera_and_composition": terms["camera"],
                "atmosphere": terms["atmosphere"],
                "color_palette": cls._color_palette_instruction(faithful_prompt, profile),
                "text_and_logo_constraints": cls._text_and_logo_constraints(faithful_prompt),
                "scene_constraints": cls._scene_constraints(faithful_prompt, profile),
                "negative_prompt": cls._negative_prompt(faithful_prompt, profile),
            },
        }

    @classmethod
    def candidate_prompt_payloads(cls, prompt: str, hints: list[str] | None = None) -> list[dict]:
        base_hints = hints or cls.optimization_hints(prompt)
        base = cls.optimized_prompt_payload(prompt, base_hints)
        profile = base["profile"]

        original_payload = {
            "task": "image_generation",
            "source": "customer_original_input",
            "original_prompt": prompt.strip(),
            "profile": cls.select_profile(prompt),
            "prompt": {
                "subject": prompt.strip(),
                "raw_text": prompt.strip(),
            },
        }
        candidates = [
            {
                "id": "original",
                "title": "客户原始输入",
                "estimated_score": 0.0,
                "why": "不做系统改写，完全保留客户原始描述，适合客户坚持原文时选择。",
                "summary": {
                    "原始输入": prompt.strip(),
                    "处理方式": "不改写；直接按客户原文提交。",
                    "风险": "可能保留占位符、文字/logo 不稳定、主体层级不够清晰等问题。",
                },
                "optimization_hints": [],
                "optimized_prompt": original_payload,
            }
        ]
        variants = cls._candidate_variants(str(profile))

        for variant in variants:
            optimized = deepcopy(base)
            optimized["source"] = "quality_reference_candidate_optimizer"
            optimized["candidate_id"] = variant["id"]
            optimized["prompt"]["camera_and_composition"] = cls._combine_instruction(
                str(variant["camera"]),
                str(base["prompt"]["camera_and_composition"]),
            )
            optimized["prompt"]["atmosphere"] = cls._combine_instruction(
                str(variant["atmosphere"]),
                str(base["prompt"]["atmosphere"]),
            )
            optimized["prompt"]["scene_constraints"] = list(
                dict.fromkeys([*base["prompt"]["scene_constraints"], *variant["constraints"]])
            )
            optimized["prompt"]["quality_priority"] = variant["quality_priority"]
            optimized["prompt"]["optimization_strategy"] = variant["strategy"]
            candidates.append(
                {
                    "id": variant["id"],
                    "title": variant["title"],
                    "estimated_score": variant["estimated_score"],
                    "why": variant["why"],
                    "summary": {
                        "主体": optimized["prompt"]["subject"],
                        "场景": optimized["prompt"]["environment"],
                        "光影": optimized["prompt"]["lighting"],
                        "镜头": optimized["prompt"]["camera_and_composition"],
                        "氛围": optimized["prompt"]["atmosphere"],
                        "文字/logo": optimized["prompt"]["text_and_logo_constraints"],
                        "关键约束": optimized["prompt"]["scene_constraints"],
                        "负向词": optimized["prompt"]["negative_prompt"],
                    },
                    "optimization_hints": base_hints,
                    "optimized_prompt": optimized,
                }
            )

        return candidates

    @staticmethod
    def _strip_placeholders(prompt: str) -> str:
        prompt = re.sub(r"\[([^\[\]]+)\]", r"\1", prompt)
        prompt = re.sub(
            r"(?<![A-Za-z0-9])i\s*phone\s*air(?![A-Za-z0-9])",
            "iPhone Air",
            prompt,
            flags=re.IGNORECASE,
        )
        return re.sub(r"(?<![A-Za-z0-9])iphone(?![A-Za-z0-9])", "iPhone", prompt, flags=re.IGNORECASE)

    @staticmethod
    def _mentions_any(text: str, tokens: tuple[str, ...]) -> bool:
        return any(token in text for token in tokens)

    @classmethod
    def _mentions_text_or_logo(cls, prompt: str) -> bool:
        normalized = prompt.lower()
        return cls._mentions_any(
            normalized,
            ("logo", "brand", "label", "typography", "text", "word", "iphone", "i phone"),
        ) or cls._mentions_any(prompt, ("标志", "名称", "文字", "标签", "品牌", "字样", "字体"))

    @classmethod
    def _environment_instruction(cls, prompt: str) -> str:
        if cls._mentions_any(
            prompt,
            (
                "城市",
                "街道",
                "室内",
                "户外",
                "森林",
                "海边",
                "山",
                "草地",
                "草甸",
                "天空",
                "海报",
                "背景",
                "场景",
                "客厅",
                "沙发",
                "餐厅",
                "街口",
                "走廊",
            ),
        ):
            return f"保留原文明确写出的场景和空间关系：{prompt}"
        return "原文未明确指定环境；使用简洁背景突出主体，不新增额外地点、道具或叙事元素。"

    @classmethod
    def _color_palette_instruction(cls, prompt: str, profile: str) -> str:
        if cls._mentions_any(prompt, ("红", "蓝", "绿", "黄", "黑", "白", "金", "银", "紫", "霓虹", "暖色", "冷色", "饱和")):
            return f"保留原文颜色、材质和氛围要求，并按 {profile} 场景控制色彩层级。"
        return f"use a controlled color palette appropriate for the {profile} profile, without introducing new visual themes"

    @classmethod
    def _text_and_logo_constraints(cls, prompt: str) -> str:
        if cls._mentions_text_or_logo(prompt):
            return "只渲染原文明确要求的 logo、名称、标签或文字；保持清晰可读，避免乱码、重复字样和额外品牌。"
        return "除非原文明确要求，不生成额外文字、logo、水印、签名或随机字母。"

    @classmethod
    def _scene_constraints(cls, prompt: str, profile: str) -> list[str]:
        constraints = [
            "完整保留原文明确写出的主体、数量、动作和场景元素。",
            "不要添加原文没有的物品、品牌、角色、植物、地标或道具。",
            "所有优化只用于明确画面层级、光影、构图和质量约束，不改变用户意图。",
        ]
        profile_constraints = {
            "storyboard": "保持原文叙事步骤、镜头数量意图、角色关系和对白走向一致；每帧必须有差异化景别或机位。",
            "product": "保持原文产品的数量、形状、材质、标签和使用场景一致。",
            "poster": "保持原文海报主题和信息层级清晰，避免为了装饰加入新叙事元素。",
            "portrait": "保持原文人物身份、姿态、服装和表情方向一致。",
            "character": "保持原文角色设定、服装、配件和比例一致。",
            "ui": "保持原文界面类型、屏幕内容和布局状态一致。",
            "default": "保持原文主体可辨识，避免把简单描述改成其他题材。",
        }
        constraints.append(profile_constraints.get(profile, profile_constraints["default"]))
        if cls._mentions_text_or_logo(prompt):
            constraints.append("只呈现原文要求的文字或标识，不补写额外营销词。")
        return constraints

    @classmethod
    def _negative_prompt(cls, prompt: str, profile: str) -> list[str]:
        negatives = [
            "low resolution",
            "blurry",
            "watermark",
            "incoherent composition",
            "unrequested objects",
            "unrequested brands",
            "unwanted text",
        ]
        profile_negatives = {
            "storyboard": (
                "repeated identical panels",
                "inconsistent character identity",
                "missing storyboard labels",
                "confusing shot order",
            ),
            "product": ("warped product geometry", "duplicated product", "incorrect product count"),
            "poster": ("overcrowded layout", "broken focal hierarchy", "unreadable typography"),
            "portrait": ("distorted face", "unnatural skin texture", "extra fingers"),
            "character": ("inconsistent costume", "broken anatomy", "mismatched accessories"),
            "ui": ("garbled UI text", "misaligned layout", "unreadable interface"),
            "default": ("subject drift", "extra props", "style conflict"),
        }
        negatives.extend(profile_negatives.get(profile, profile_negatives["default"]))
        if cls._mentions_text_or_logo(prompt):
            negatives.extend(("garbled requested text", "misspelled logo", "extra logos"))
        if cls._mentions_any(prompt.lower(), ("iphone", "i phone", "phone")) or "手机" in prompt:
            negatives.extend(("warped phone", "duplicated phone"))
        return list(dict.fromkeys(negatives))

    @staticmethod
    def _combine_instruction(primary: str, reference: str) -> str:
        return f"{primary}; reference profile guidance: {reference}"

    @classmethod
    def _candidate_variants(cls, profile: str) -> tuple[dict, dict, dict]:
        generic = (
            {
                "id": f"{profile}_subject_anchor",
                "title": "方案 A：主体忠实强化",
                "estimated_score": 9.0,
                "why": "优先锁定原文主体和可验证细节，适合需要最大程度避免跑题的结果。",
                "strategy": "preserve original subject first, then clarify visible details and hierarchy",
                "camera": "clear subject-first composition, readable framing, stable focal point",
                "atmosphere": "coherent and polished rendering that stays close to the original prompt",
                "constraints": [
                    "do not replace the original subject with another category",
                    "do not add story elements absent from the original prompt",
                    "make the main subject easy to verify at first glance",
                ],
                "quality_priority": ["original subject fidelity", "readable silhouette", "clean composition"],
            },
            {
                "id": f"{profile}_composition_light",
                "title": "方案 B：构图光影优化",
                "estimated_score": 8.8,
                "why": "在不改变题材的前提下强化镜头、光影和空间层次，适合追求画面完成度。",
                "strategy": "improve lighting, depth, and composition while preserving every original scene element",
                "camera": "balanced composition with clear foreground, midground, background, and controlled depth of field",
                "atmosphere": "refined lighting, consistent mood, clean depth separation",
                "constraints": [
                    "lighting and camera choices must support the original prompt",
                    "do not introduce new locations, props, brands, or characters",
                    "keep the composition uncluttered and easy to read",
                ],
                "quality_priority": ["lighting control", "spatial hierarchy", "composition clarity"],
            },
            {
                "id": f"{profile}_detail_control",
                "title": "方案 C：细节约束增强",
                "estimated_score": 8.7,
                "why": "强化材质、纹理和负向约束，适合减少文字、结构和细节伪影。",
                "strategy": "add material detail and artifact controls without adding new subject matter",
                "camera": "detail-preserving view with sharp edges, stable geometry, and controlled visual density",
                "atmosphere": "high-detail finish with restrained styling and no unrequested decorative additions",
                "constraints": [
                    "preserve material and texture requirements from the original prompt",
                    "avoid accidental text, duplicated subjects, and unrequested objects",
                    "keep all added quality terms subordinate to the original intent",
                ],
                "quality_priority": ["material detail", "artifact reduction", "intent preservation"],
            },
        )
        overrides = {
            "storyboard": (
                {
                    **generic[0],
                    "title": "方案 A：分镜结构锚定",
                    "camera": "16:9 grid-based production board, numbered storyboard frames, clear shot-size variation, readable top creative bar",
                    "atmosphere": "professional director planning sheet that preserves the source story beats and keeps character identity consistent",
                    "quality_priority": ["story beat fidelity", "shot variety", "character continuity"],
                    "constraints": [
                        "split each source step into a clear visual beat before merging into the final board",
                        "do not omit required production-board sections",
                        "avoid repeated identical camera angles across adjacent frames",
                    ],
                },
                {
                    **generic[1],
                    "title": "方案 B：机位与动线强化",
                    "camera": "overhead movement map plus labeled camera positions, wide / medium / close-up / macro shots arranged in a clean grid",
                    "atmosphere": "cinematic planning rhythm with indoor-to-outdoor movement and visible light-quality transitions",
                    "quality_priority": ["camera blocking", "movement path", "lighting transition"],
                    "constraints": [
                        "show camera positions and movement route as part of the environment design section",
                        "use varied shot sizes and movement types across all storyboard frames",
                        "keep props and spatial continuity readable",
                    ],
                },
                {
                    **generic[2],
                    "title": "方案 C：角色与版式控制",
                    "camera": "model-sheet reference views, concise labels, clean section hierarchy, stable 16:9 production-board framing",
                    "atmosphere": "coherent visual development board with restrained typography, texture notes, audio tone, and negative constraints",
                    "quality_priority": ["identity lock", "layout readability", "artifact reduction"],
                    "constraints": [
                        "keep the same faces, outfits, hair, accessories, and key props in every frame",
                        "make section labels concise and readable without dumping raw JSON into the image",
                        "avoid garbled labels, cramped panels, and decorative clutter",
                    ],
                },
            ),
            "product": (
                {
                    **generic[0],
                    "title": "方案 A：产品主体锚定",
                    "camera": "premium product-first framing, clean hero composition, sharp product edges",
                    "atmosphere": "commercial product polish, credible scale, controlled reflections",
                    "quality_priority": ["product fidelity", "label control", "clean hero composition"],
                },
                {
                    **generic[1],
                    "title": "方案 B：产品场景层级",
                    "camera": "three-quarter product view with original scene elements kept secondary and organized",
                    "atmosphere": "advertising-grade scene depth that preserves only the environment described by the user",
                    "quality_priority": ["scene hierarchy", "product visibility", "lighting control"],
                },
                {
                    **generic[2],
                    "title": "方案 C：材质与文字约束",
                    "camera": "detail-focused product view with stable geometry and readable requested labels",
                    "atmosphere": "premium material rendering with restrained styling and clean brand/text control",
                    "quality_priority": ["material realism", "requested text control", "artifact reduction"],
                },
            ),
            "poster": (
                {
                    **generic[0],
                    "title": "方案 A：海报主题层级",
                    "camera": "poster-first focal hierarchy, readable layout, generous but purposeful negative space",
                    "atmosphere": "editorial poster finish that keeps the original theme and scene unchanged",
                    "quality_priority": ["theme fidelity", "layout readability", "poster impact"],
                },
                {
                    **generic[1],
                    "title": "方案 B：海报构图光影",
                    "camera": "dynamic poster composition with clear focal path and controlled atmospheric depth",
                    "atmosphere": "polished illustration or poster mood aligned with the original prompt",
                    "quality_priority": ["focal hierarchy", "lighting depth", "clean layout"],
                },
                {
                    **generic[2],
                    "title": "方案 C：印刷细节控制",
                    "camera": "print-aware composition with crisp edges, clean typography-safe spacing, stable detail",
                    "atmosphere": "refined print finish, controlled texture, no unrequested decorative clutter",
                    "quality_priority": ["print clarity", "texture control", "artifact reduction"],
                },
            ),
        }
        return overrides.get(profile, generic)

    @classmethod
    def _prompt_quality_without_hints(cls, prompt: str) -> dict:
        normalized = prompt.lower()
        matched_dimensions = [
            dimension
            for dimension, markers in cls.HIGH_QUALITY_MARKERS.items()
            if any(marker.lower() in normalized for marker in markers)
        ]
        missing_dimensions = [
            item["dimension"]
            for item in cls.QUALITY_RUBRIC
            if item["dimension"] != "coherence" and item["dimension"] not in matched_dimensions
        ]
        if len(prompt.strip()) >= 8:
            matched_dimensions.insert(0, "subject")
            if "subject" in missing_dimensions:
                missing_dimensions.remove("subject")

        return {
            "matched_dimensions": matched_dimensions,
            "missing_dimensions": missing_dimensions,
        }
