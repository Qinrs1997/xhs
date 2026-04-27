from types import SimpleNamespace

import pytest

from app.ai.services.xhs import content as content_module
from app.ai.services.xhs import outline as outline_module
from app.ai.services.xhs.content import XHSContentService
from app.ai.services.xhs.outline import XHSOutlineService


async def _noop_sleep(_seconds: float):
    return None


@pytest.mark.asyncio
async def test_content_generation_retries_invalid_json(monkeypatch):
    calls: list[str] = []

    async def fake_get(*_args, **_kwargs):
        return "base content prompt"

    async def fake_chat(**kwargs):
        calls.append(kwargs["message"])
        if len(calls) == 1:
            return SimpleNamespace(content="not json")
        return SimpleNamespace(
            content='{"titles":["标题"],"copywriting":"正文","tags":["标签"],"emoji_title":"✨ 标题"}'
        )

    monkeypatch.setattr(content_module.prompts, "get", fake_get)
    monkeypatch.setattr(content_module.ai, "chat", fake_chat)
    monkeypatch.setattr(content_module.ai_config, "chat_enabled", True, raising=False)
    monkeypatch.setattr(content_module.asyncio, "sleep", _noop_sleep)

    result = await XHSContentService().generate_content(topic="测试主题")

    assert result.copywriting == "正文"
    assert len(calls) == 2
    assert "只返回 JSON" in calls[1]


@pytest.mark.asyncio
async def test_outline_generation_retries_empty_pages_with_same_search_context(monkeypatch):
    calls: list[str] = []

    async def fake_get(*_args, **_kwargs):
        return "base outline prompt"

    async def fake_chat(**kwargs):
        calls.append(kwargs["message"])
        if len(calls) == 1:
            return SimpleNamespace(content="")
        return SimpleNamespace(content="[封面]\n【标题】搜索主题\n正文内容")

    monkeypatch.setattr(outline_module.prompts, "get", fake_get)
    monkeypatch.setattr(outline_module.ai, "chat", fake_chat)
    monkeypatch.setattr(outline_module.ai_config, "chat_enabled", True, raising=False)
    monkeypatch.setattr(outline_module.asyncio, "sleep", _noop_sleep)

    result = await XHSOutlineService().generate_outline(
        topic="测试主题",
        page_count=3,
        search_context="搜索总结: 这是已保存的搜索资料",
    )

    assert result.pages[0].title == "搜索主题"
    assert len(calls) == 2
    assert "搜索总结" in calls[0]
    assert "上一次输出无法解析" in calls[1]
    assert "搜索总结" in calls[1]
