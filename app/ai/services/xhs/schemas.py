from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


class XHSOutlineRequest(BaseModel):
    topic: str = Field(..., description="Xiaohongshu topic")
    images: Optional[List[str]] = Field(None, description="Reference images")
    template_id: Optional[int] = Field(None, description="Template ID")
    model: Optional[str] = Field(None, description="AI model name")
    style_prompt: Optional[str] = Field(None, description="Template style prompt")
    content_prompt: Optional[str] = Field(None, description="Rendered content-level prompt")
    page_count: Optional[int] = Field(None, description="Requested page count")
    tone: Optional[str] = Field(None, description="Content tone: casual/professional/playful/literary")
    language: Optional[str] = Field("zh", description="Output language: zh/en")
    search_id: Optional[int] = Field(None, description="Related search history ID")
    search_context: Optional[str] = Field(
        None,
        description="Search summary/results selected by the frontend; used as direct LLM context",
    )
    use_search_context: Optional[bool] = Field(
        False, description="Whether to merge search summary into the outline prompt"
    )


class XHSPage(BaseModel):
    index: int = Field(..., description="Page index")
    content: str = Field(..., description="Page content")
    page_type: str = Field("content", description="Page type: cover/content/summary")
    title: Optional[str] = Field(None, description="Optional page title")
    image_prompt: Optional[str] = Field(None, description="Optional image prompt supplied by the frontend")


class XHSOutlineResponse(BaseModel):
    task_id: Optional[str] = Field(None, description="Created draft task ID")
    outline: str = Field(..., description="Raw outline text")
    pages: List[XHSPage] = Field(..., description="Parsed page list")


class XHSContentRequest(BaseModel):
    topic: str
    outline: Optional[str] = None
    pages: Optional[Union[List[dict], int]] = Field(None, description="Page list or page count")
    style: Optional[str] = Field("casual", description="Style: casual/professional/humorous")
    model: Optional[str] = Field(None, description="AI model name")
    task_id: Optional[int] = Field(None, description="Related task ID")


class XHSContentResponse(BaseModel):
    titles: List[str]
    copywriting: str
    tags: List[str]
    emoji_title: Optional[str] = None


class XHSImageStreamRequest(BaseModel):
    pages: List[XHSPage]
    outline: Optional[str] = Field("", description="Outline text")
    user_topic: Optional[str] = Field("", description="Original user topic")
    task_id: Optional[int] = Field(None, description="Related task ID")
    images: Optional[List[str]] = None
    image_size: Optional[str] = Field(None, description="Image size: 1024x1024/1024x1792/1792x1024")
    image_quality: Optional[str] = Field(None, description="Image quality: standard/hd")
    image_style: Optional[str] = Field(None, description="Image style: natural/vivid")
    image_engine: Optional[str] = Field(None, description="Configured image engine")
    negative_prompt: Optional[str] = Field(None, description="Negative prompt")
    extra_params: Optional[dict] = Field(None, description="Additional provider-specific image params")
    images_per_page: Optional[int] = Field(1, ge=1, le=4, description="Number of candidate images per page")
    style_prompt: Optional[str] = Field(
        None,
        description=(
            "Template style prompt; appended to every page's final image "
            "prompt as a hard style constraint so switching templates "
            "actually changes the generated images."
        ),
    )
    negative_style_prompt: Optional[str] = Field(
        None,
        description=(
            "Template-level negative style (must-not-appear elements); "
            "appended as a hard negative constraint on every page."
        ),
    )
    generation_mode: Optional[Literal["per_page", "batch_grid"]] = Field(
        "per_page",
        description=(
            "per_page: 每页独立调用图片 API(质量最佳,默认); "
            "batch_grid: 按 NxM 网格分批生成合成大图 + 后端切割(每批最多 4 页)"
        ),
    )
    grid_config: Optional[dict] = Field(
        None,
        description=(
            'batch_grid 专用: {"rows":2,"cols":2,"cell_size":"512x896",'
            '"gap_px":16,"split_upscale_enabled":true,'
            '"split_target_cell_size":"1024x1792"}; '
            'split_upscale_enabled=false 时严格保存原始 crop 切割图; '
            '为空时用 settings.toml [ai.image.batch_grid] 默认'
        ),
    )


class PromptsBatchRequest(BaseModel):
    """Batch image prompt generation request."""

    topic: str = Field(..., description="Topic")
    template_id: Optional[int] = Field(None, description="Template ID for style fallback")
    style_prompt: Optional[str] = Field(None, description="Template or page style prompt")
    negative_style_prompt: Optional[str] = Field(
        None,
        description=("Template-level negative style; elements that must NOT appear in any page."),
    )
    pages: List[dict] = Field(..., description="Page list")
    task_id: Optional[int] = Field(None, description="Related task ID for persisting generated prompts")


class PromptOptimizeRequest(BaseModel):
    """Single image prompt optimization request."""

    prompt: str = Field(..., description="Original prompt")
    page_content: Optional[str] = Field(None, description="Page content context")
    page_type: Optional[str] = Field(None, description="Page type: cover/content/summary")
    task_id: Optional[int] = Field(None, description="Related task ID")
    page_index: Optional[int] = Field(None, description="Zero-based page index")


class ImageRegenerateRequest(BaseModel):
    """Single page regenerate request."""

    page: XHSPage = Field(..., description="Page to regenerate")
    outline: str = Field("", description="Outline context")
    user_topic: str = Field("", description="Original user topic")
    images: Optional[List[str]] = Field(None, description="Reference images")
    image_size: Optional[str] = Field(None, description="Image size override")
    image_quality: Optional[str] = Field(None, description="Image quality override")
    image_style: Optional[str] = Field(None, description="Image style override")
    image_engine: Optional[str] = Field(None, description="Configured image engine")
    negative_prompt: Optional[str] = Field(None, description="Negative prompt")
    extra_params: Optional[dict] = Field(None, description="Additional provider-specific image params")
    task_id: Optional[int] = Field(None, description="Related task ID")
    page_index: Optional[int] = Field(None, description="Zero-based page index")
    style_prompt: Optional[str] = Field(
        None,
        description=("Template style prompt; appended to the final image prompt as a hard style constraint."),
    )
    negative_style_prompt: Optional[str] = Field(
        None,
        description="Template-level negative style constraint.",
    )


class BatchGridRegenerateRequest(BaseModel):
    """Batch grid regenerate request (省钱模式下对选中页面做一次合成重绘)。

    前端行为:用户在省钱模式的结果页勾选 2/3/4 张页面,点"🔄 重绘选中"。
    后端行为:
      1. 使用 2x2 竖版候选格,2/3 张时其余格留白,4 张时填满。
      2. 调 1 次图片 API 出合成大图 + Pillow 切格。
      3. 按 ``page_indexes`` 的顺序,把切出来的 N 张 cell 覆盖回对应页。

    成本:无论用户选 2/3/4 张,都只消耗 **1 次** API 调用,保持省钱模式初衷。
    """

    task_id: Optional[int] = Field(None, description="Related task ID")
    page_indexes: List[int] = Field(
        ...,
        min_length=2,
        max_length=4,
        description="Zero-based page indexes to regenerate (2-4 items)",
    )
    pages: List[XHSPage] = Field(
        ...,
        description=(
            "All task pages; backend picks rows from ``page_indexes`` but keeps "
            "the whole list for outline / style continuity context."
        ),
    )
    outline: str = Field("", description="Outline context")
    user_topic: str = Field("", description="Original user topic")
    image_engine: Optional[str] = Field(None, description="Configured image engine")
    image_quality: Optional[str] = Field(None, description="Image quality override")
    image_style: Optional[str] = Field(None, description="Image style override")
    negative_prompt: Optional[str] = Field(None, description="Negative prompt")
    extra_params: Optional[dict] = Field(None, description="Additional provider-specific image params")
    style_prompt: Optional[str] = Field(None, description="Template-level style prompt (hard constraint)")
    negative_style_prompt: Optional[str] = Field(None, description="Template-level negative style constraint")
    grid_config: Optional[dict] = Field(
        None,
        description=(
            "Optional grid layout override; when None the backend uses a "
            "2x2 vertical contact sheet and leaves unused cells blank."
        ),
    )


class BatchGridRegenerateCellResult(BaseModel):
    """Single cell result returned by ``/image/batch_grid/regenerate``."""

    page_index: int = Field(..., description="Zero-based page index that was replaced")
    status: Literal["success", "failed"] = Field(..., description="Per-cell status")
    url: Optional[str] = Field(None, description="Original image URL (local)")
    image_url: Optional[str] = Field(None, description="Alias of ``url``")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail URL (local)")
    original_url: Optional[str] = Field(None, description="Original image URL (local)")
    width: Optional[int] = Field(None, description="Original width")
    height: Optional[int] = Field(None, description="Original height")
    error: Optional[str] = Field(None, description="Per-cell failure reason")


class BatchGridRegenerateResponse(BaseModel):
    """Response payload for batch_grid subset regenerate."""

    task_id: str = Field(..., description="Internal batch task id")
    rows: int = Field(..., description="Resolved grid rows used for this call")
    cols: int = Field(..., description="Resolved grid cols used for this call")
    mode: Literal["batch_grid", "per_page_fallback"] = Field(
        ...,
        description=(
            "Actual execution mode: batch_grid=one composite API call. "
            "per_page_fallback is kept only for backward compatibility with "
            "older responses; current subset regenerate does not silently "
            "downgrade to extra per_page image calls."
        ),
    )
    fallback_reason: Optional[str] = Field(None, description="Failure reason when composite generation cannot finish")
    cells: List[BatchGridRegenerateCellResult] = Field(
        ..., description="Per-page results, same order as request.page_indexes"
    )
    success: int = Field(..., description="Successful page count")
    failed: int = Field(..., description="Failed page count")


class CopywritingGenerateRequest(BaseModel):
    """Copywriting generation request."""

    task_id: Optional[int] = Field(None, description="Related task ID")
    topic: str = Field(..., description="Topic")
    pages: List[dict] = Field(..., description="Page list")
    style: Optional[str] = Field(
        "casual",
        description="Style: casual/professional/humorous/playful/literary",
    )
    copy_length: Optional[str] = Field("medium", description="Copy length: short/medium/long")
    tag_count: Optional[int] = Field(5, ge=1, le=15, description="Number of tags to generate")
    title_count: Optional[int] = Field(3, ge=1, le=5, description="Number of candidate titles")
    include_emoji: Optional[bool] = Field(True, description="Whether to include emoji in titles")


class BatchFromSearchRequest(BaseModel):
    """Batch creation request driven by search results."""

    topic: str = Field(..., min_length=1, max_length=200, description="Topic")
    count: int = Field(default=7, ge=1, le=15, description="Number of results")
    style: Optional[str] = Field(
        "casual",
        description="Copy style: casual/professional/humorous/playful/literary",
    )
    search_provider: Optional[str] = Field(None, description="Search provider: duckduckgo/tavily/serper/searxng")
    max_search_results: int = Field(default=8, ge=3, le=20, description="Maximum number of search hits")
    copy_length: Optional[str] = Field("medium", description="Copy length: short/medium/long")
    include_emoji: Optional[bool] = Field(True, description="Whether to include emoji in titles")
    search_history_id: Optional[int] = Field(None, description="Related search history record ID")


class BatchTaskResult(BaseModel):
    """Single batch task result."""

    task_id: Optional[int] = Field(None, description="Created task ID")
    angle_title: str = Field(..., description="Angle title")
    title: Optional[str] = Field(None, description="Generated title")
    content: Optional[str] = Field(None, description="Generated copywriting")
    tags: Optional[List[str]] = Field(None, description="Generated tags")
    status: str = Field(..., description="Status: success/failed")
    error: Optional[str] = Field(None, description="Failure reason")


class SearchSource(BaseModel):
    """Search result source."""

    title: str = Field(..., description="Source title")
    url: str = Field(..., description="Source URL")
    snippet: Optional[str] = Field(None, description="Source snippet")


class BatchFromSearchResponse(BaseModel):
    """Batch from search response."""

    topic: str = Field(..., description="Search topic")
    tasks: List[BatchTaskResult] = Field(..., description="Generated task list")
    search_sources: List[SearchSource] = Field(default_factory=list, description="Search sources")
    total: int = Field(..., description="Total tasks")
    success: int = Field(..., description="Successful tasks")
    failed: int = Field(..., description="Failed tasks")
