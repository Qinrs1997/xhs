"""小红书模板模型

存储小红书图文生成的模板数据（美食探店、穿搭推荐等）。
"""
from typing import Optional
from sqlalchemy import String, Text, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class XHSTemplate(BaseModel):
    """小红书模板"""
    __tablename__ = "xhs_templates"

    # 基本信息
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="模板名称"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="模板描述"
    )
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="分类: food/fashion/travel 等"
    )

    # 展示信息
    cover_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="封面预览图 URL"
    )
    default_topic: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="默认主题文案"
    )

    # AI 参数
    style_prompt: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="AI 图片风格提示词"
    )
    negative_style_prompt: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "模板级负向风格约束,禁止出现的元素列表文本,由 /image/stream 和 "
            "/xhs/prompts 硬注入到最终 prompt"
        ),
    )
    # 正文级提示词模板，支持 Jinja 变量（如 {{ topic }} / {{ keywords }}）
    # 为空时仅使用 style_prompt 控制图风格；填写后会影响大纲文案结构
    content_prompt_template: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="正文级提示词模板(Jinja)，用 {{ topic }} 插值"
    )
    page_count: Mapped[int] = mapped_column(
        Integer, default=6, comment="默认生成页数"
    )

    # ==================== 生图模式（成本/画质 双档） ====================
    # per_page：每页一次 API 调用（质量最佳，默认，老模板零行为变化）
    # batch_grid：一次 API 出 NxM 网格图 + 后端切割（成本降约 4x，画质稍降）
    image_generation_mode: Mapped[str] = mapped_column(
        String(16),
        default="per_page",
        nullable=False,
        comment=(
            "生图模式: per_page=每页独立生成(质量最佳); "
            "batch_grid=一次API出网格图+后端切割(成本降约4x)"
        ),
    )
    # batch_grid 模式专用布局配置 JSON：
    # {"rows":2, "cols":2, "cell_size":"1024x1024", "gap_px":16,
    #  "split_upscale_enabled":true, "split_target_cell_size":"1024x1792"}
    # 为空时使用 settings.toml [ai.image.batch_grid] 的默认值
    image_grid_config: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment=(
            "batch_grid 模式的网格布局配置 JSON "
            "(rows/cols/cell_size/gap_px/split_upscale_enabled/split_target_cell_size),"
            "为空用 settings.toml 默认"
        ),
    )

    # 示例页面（JSON 数组，模板详情时展示）
    # 格式: [{"page_num": 1, "type": "cover", "title": "...", "content": "...", "example_image_url": "..."}]
    example_pages: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="示例页面 (JSON)"
    )

    # 热门/新品标记
    is_new: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否为新模板"
    )
    is_hot: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否为热门模板"
    )
    use_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="使用次数"
    )

    # ==================== 商业化字段 ====================
    # 价格，单位:积分(credits)；0 表示免费
    price: Mapped[int] = mapped_column(
        Integer, default=0, comment="使用该模板单次消耗的积分（0=免费）"
    )
    # 是否为 Pro/VIP 专享模板（即使免费，普通用户也无法使用）
    is_pro: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否 VIP 专享"
    )
    # 作者（创作者）用户 ID；平台官方模板留空；用于后续分账/署名
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="模板作者 user_id（官方模板为 NULL）"
    )
    # 标签数组，用于检索/筛选，例如 ["护肤", "干皮", "新手"]
    tags: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True, comment="标签数组 (JSON)"
    )

    # 排序和状态
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, comment="排序权重（越大越前）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, comment="是否启用"
    )

    def __repr__(self) -> str:
        return f"<XHSTemplate(id={self.id}, name='{self.name}', category='{self.category}')>"
