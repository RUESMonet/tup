import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from src.agents.prompt_skill_agent import PromptSkillAgent
from src.api.image_routes import MAX_PROMPT_LENGTH, require_high_cost_access
from src.dependencies import get_prompt_skill_agent
from src.models.prompt_skill import PromptSkillRequest, PromptSkillResponse


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class PromptOptimizeRequest(PromptSkillRequest):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


@router.post("/prompt/optimize", response_model=PromptSkillResponse, dependencies=[Depends(require_high_cost_access)])
async def optimize_prompt(
    request: PromptOptimizeRequest,
    agent: PromptSkillAgent = Depends(get_prompt_skill_agent),
) -> PromptSkillResponse:
    try:
        response = await agent.optimize(
            PromptSkillRequest(
                prompt=request.prompt,
                action_type=request.action_type,
                source_images=request.source_images,
                mask_image=request.mask_image,
                conversation_id=request.conversation_id,
                conversation_context=request.conversation_context,
                character_anchors=request.character_anchors,
                params=request.params,
                defects=request.defects,
            )
        )
    except RuntimeError as exc:
        logger.exception("Prompt Skill optimization failed")
        raise HTTPException(status_code=502, detail="Prompt 美化失败，请稍后重试或检查模型配置。") from exc
    return response
