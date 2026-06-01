import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from src.agents.character_sheet import CharacterSheetExtractor
from src.agents.prompt_skill_agent import PromptSkillAgent
from src.api.image_routes import MAX_PROMPT_LENGTH, require_high_cost_access
from src.dependencies import get_conversation_repository, get_project_repository, get_prompt_skill_agent, require_current_user
from src.models.auth import AuthUser
from src.models.conversation import ConversationCreateRequest, ConversationDetailResponse, ConversationMessageCreateRequest, ConversationMessageResponse, ConversationResponse
from src.models.project import AssetKind
from src.models.prompt_skill import ImageSource, PromptSkillRequest, PromptSkillResponse
from src.services.conversation_repository import ConversationRepository
from src.services.project_repository import ProjectRepository


router = APIRouter(prefix="/api", tags=["conversations"])
logger = logging.getLogger(__name__)


class ConversationPromptOptimizeRequest(PromptSkillRequest):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


@router.post("/projects/{project_id}/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_project_conversation(
    project_id: str,
    request: ConversationCreateRequest,
    user: AuthUser = Depends(require_current_user),
    project_repository: ProjectRepository = Depends(get_project_repository),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationResponse:
    if await asyncio.to_thread(project_repository.get_project, user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await asyncio.to_thread(conversation_repository.create_conversation, user.id, project_id, request.title, request.summary)


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationResponse])
async def list_project_conversations(
    project_id: str,
    user: AuthUser = Depends(require_current_user),
    project_repository: ProjectRepository = Depends(get_project_repository),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> list[ConversationResponse]:
    if await asyncio.to_thread(project_repository.get_project, user.id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await asyncio.to_thread(conversation_repository.list_conversations, user.id, project_id)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    user: AuthUser = Depends(require_current_user),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationDetailResponse:
    detail = await asyncio.to_thread(conversation_repository.conversation_detail, user.id, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageResponse, status_code=status.HTTP_201_CREATED)
async def add_conversation_message(
    conversation_id: str,
    request: ConversationMessageCreateRequest,
    user: AuthUser = Depends(require_current_user),
    project_repository: ProjectRepository = Depends(get_project_repository),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationMessageResponse:
    detail = await asyncio.to_thread(conversation_repository.conversation_detail, user.id, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await asyncio.to_thread(_validate_asset_ids, user.id, detail.project_id, request.asset_ids, project_repository)
    message = await asyncio.to_thread(
        conversation_repository.add_message,
        user.id,
        conversation_id,
        request.role,
        request.content,
        request.asset_ids,
        request.prompt_snapshot,
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        await asyncio.to_thread(_upsert_character_sheet_from_message, user.id, detail.project_id, conversation_id, request, detail, conversation_repository)
    except Exception:
        logger.exception("Conversation character sheet update failed", extra={"conversation_id": conversation_id})
    return message


@router.post("/conversations/{conversation_id}/prompt/optimize", response_model=PromptSkillResponse, dependencies=[Depends(require_high_cost_access)])
async def optimize_conversation_prompt(
    conversation_id: str,
    request: ConversationPromptOptimizeRequest,
    user: AuthUser = Depends(require_current_user),
    project_repository: ProjectRepository = Depends(get_project_repository),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    agent: PromptSkillAgent = Depends(get_prompt_skill_agent),
) -> PromptSkillResponse:
    detail = await asyncio.to_thread(conversation_repository.conversation_detail, user.id, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    anchors = _character_anchors(detail)
    context = [{"role": "user", "content": message.content} for message in detail.messages[-6:] if message.role == "user"]
    source_images = await asyncio.to_thread(_resolve_prompt_sources, user.id, detail.project_id, request.source_images, project_repository)
    mask_image = await asyncio.to_thread(_resolve_prompt_mask, user.id, detail.project_id, request.mask_image, project_repository)
    try:
        response = await agent.optimize(
            PromptSkillRequest(
                prompt=request.prompt,
                action_type=request.action_type,
                source_images=source_images,
                mask_image=mask_image,
                conversation_id=conversation_id,
                conversation_context=context,
                character_anchors=anchors,
                params=request.params,
                defects=request.defects,
            )
        )
    except RuntimeError as exc:
        logger.exception("Conversation prompt optimization failed", extra={"conversation_id": conversation_id})
        raise HTTPException(status_code=502, detail="Prompt 美化失败，请稍后重试或检查模型配置。") from exc
    return response


def _resolve_prompt_sources(owner_id: str, project_id: str, sources: list[ImageSource], repository: ProjectRepository) -> list[ImageSource]:
    return [_resolve_prompt_source(owner_id, project_id, source, repository, "Source image asset not found") for source in sources]


def _resolve_prompt_mask(owner_id: str, project_id: str, source: ImageSource | None, repository: ProjectRepository) -> ImageSource | None:
    if source is None:
        return None
    return _resolve_prompt_source(owner_id, project_id, source, repository, "Mask image asset not found")


def _resolve_prompt_source(owner_id: str, project_id: str, source: ImageSource, repository: ProjectRepository, error_detail: str) -> ImageSource:
    if source.url:
        raise HTTPException(status_code=400, detail="Conversation prompt image sources must use project asset IDs")
    if source.asset_id is None:
        raise HTTPException(status_code=400, detail="Conversation prompt image sources must use project asset IDs")
    asset = repository.get_asset(owner_id, project_id, source.asset_id)
    if asset is None or asset.kind != AssetKind.image:
        raise HTTPException(status_code=404, detail=error_detail)
    return ImageSource(asset_id=asset.id, media_type=asset.media_type, role=source.role, metadata={"project_id": project_id, "filename": asset.metadata.get("filename")})


def _validate_asset_ids(owner_id: str, project_id: str, asset_ids: list[str], repository: ProjectRepository) -> None:
    for asset_id in dict.fromkeys(asset_ids):
        asset = repository.get_asset(owner_id, project_id, asset_id)
        if asset is None or asset.kind != AssetKind.image:
            raise HTTPException(status_code=404, detail="Message asset not found")


def _upsert_character_sheet_from_message(
    owner_id: str,
    project_id: str,
    conversation_id: str,
    request: ConversationMessageCreateRequest,
    detail: ConversationDetailResponse,
    repository: ConversationRepository,
) -> None:
    if request.role != "user":
        return
    existing_anchors = _character_anchors(detail)
    extractor = CharacterSheetExtractor()
    if not extractor.should_extract(request.content) and not existing_anchors:
        return
    sheet = extractor.extract(request.content, existing_anchors=existing_anchors)
    if not sheet.identity_anchors:
        return
    repository.upsert_character_sheet(
        owner_id,
        project_id,
        conversation_id,
        sheet.name,
        sheet.identity_anchors,
        sheet.visual_traits,
        sheet.locked_prompt_text,
        request.asset_ids,
    )


def _character_anchors(detail: ConversationDetailResponse) -> list[str]:
    anchors: list[str] = []
    for sheet in detail.character_sheets:
        anchors.extend(sheet.identity_anchors)
    return list(dict.fromkeys(anchor for anchor in anchors if anchor))
