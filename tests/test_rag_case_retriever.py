import pytest

from src.agents.prompt_case_library import CURATED_FALLBACK_CASES, PromptCaseLibrary, parse_upstream_markdown, retrieve_prompt_cases
from src.agents.rag_case_retriever import RagCaseRetriever


@pytest.mark.asyncio
async def test_retriever_prefers_local_awesome_cases():
    retriever = RagCaseRetriever()

    cases = await retriever.retrieve("高级手表产品广告，棚拍反光", limit=3)

    assert cases
    assert cases[0]["profile"] == "product"
    assert cases[0]["source"] in {"local_awesome_cases", "curated_fallback"}
    assert cases[0]["source_case"]
    assert {"id", "title", "takeaways", "visual_dna", "prompt_spec"} <= set(cases[0])
    assert "pattern" not in cases[0]
    assert "prompt_excerpt" not in cases[0]
    assert "source_path" not in cases[0]
    assert "source_url" not in cases[0]


@pytest.mark.asyncio
async def test_retriever_uses_task_type_signal_for_image_editing():
    retriever = RagCaseRetriever()

    cases = await retriever.retrieve("把背景换成雪山，保持人物不变", task_type="edit", limit=4)

    serialized = " ".join(str(case) for case in cases).lower()
    assert cases
    assert "preserve" in serialized or "保留" in serialized


def test_parse_upstream_markdown_returns_empty_for_unparseable_local_file():
    parsed = parse_upstream_markdown("# Translated cases without recognizable profile sections")

    assert parsed == []
    assert parsed != list(CURATED_FALLBACK_CASES)


@pytest.mark.asyncio
async def test_prompt_case_library_falls_back_when_local_and_remote_fail(monkeypatch):
    library = PromptCaseLibrary(local_root="/missing/local/cases")

    async def fail_fetch():
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(library, "_fetch_upstream_corpus", fail_fetch)

    cases = await library.get_cases()

    assert cases
    assert any(case["source_case"] for case in cases)
    assert any(case.get("visual_dna") and case.get("prompt_spec") for case in cases)
    assert all("source_path" not in case and "source_url" not in case for case in cases)


@pytest.mark.asyncio
async def test_retrieve_prompt_cases_accepts_task_type():
    cases = await retrieve_prompt_cases("角色一致，白发蓝眼女孩，多场景", task_type="character_consistency", limit=5)

    assert cases
    assert any(case["profile"] == "character" for case in cases)
