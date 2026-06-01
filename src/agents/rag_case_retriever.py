from typing import Any

from src.agents.prompt_case_library import prompt_case_library, retrieve_prompt_cases


class RagCaseRetriever:
    def __init__(self, limit: int = 5):
        self.limit = limit

    async def retrieve(self, prompt: str, *, task_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        selected = await retrieve_prompt_cases(prompt, limit=limit or self.limit, task_type=task_type)
        return [self._case_for_response(case) for case in selected]

    async def source_freshness(self) -> dict[str, Any]:
        cases = await prompt_case_library.get_cases()
        sources = sorted({str(case.get("source") or "unknown") for case in cases})
        local_count = sum(1 for case in cases if case.get("source") == "local_awesome_cases")
        return {
            "source": ",".join(sources) if sources else "empty",
            "case_count": len(cases),
            "local_case_count": local_count,
            "strategy": "local_awesome_markdown_first_then_upstream_then_curated_fallback",
        }

    @staticmethod
    def _case_for_response(case: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "id",
            "profile",
            "title",
            "source_case",
            "source",
            "when_to_use",
            "task_types",
            "takeaways",
            "tags",
            "aesthetic_score",
            "visual_dna",
            "prompt_spec",
        )
        return {key: case.get(key) for key in keys if key in case}
