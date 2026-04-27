#!/usr/bin/env python3
"""
硅基流动 API 测试脚本

测试硅基流动 AI 功能是否正常工作
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.ai.config import ai_config
from app.ai.providers import get_provider


async def test_chat_completion():
    """测试普通聊天补全"""
    print("=" * 60)
    print("测试 1: 普通聊天补全")
    print("=" * 60)

    try:
        # 获取 AI Provider
        provider = get_provider()
        print(f"✓ 使用 Provider: {provider.name}")
        print(f"✓ API Base URL: {ai_config.openai.base_url}")
        print(f"✓ 模型: {ai_config.openai.chat_model}")
        print()

        # 发送测试消息
        messages = [
            {"role": "user", "content": "你好，请用一句话介绍一下你自己"}
        ]

        print("发送消息：你好，请用一句话介绍一下你自己")
        print("等待响应...\n")

        response = await provider.chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=100
        )

        print("响应内容:")
        print("-" * 60)
        print(response.content)
        print("-" * 60)
        print()
        print("📊 Token 使用情况:")
        print(f"  - 输入 tokens: {response.usage.get('prompt_tokens', 0)}")
        print(f"  - 输出 tokens: {response.usage.get('completion_tokens', 0)}")
        print(f"  - 总计 tokens: {response.usage.get('total_tokens', 0)}")
        print(f"  - 完成原因: {response.finish_reason}")
        print(f"  - 模型: {response.model}")
        print()
        print("✅ 测试成功！")

    except Exception as e:
        print(f"❌ 测试失败: {e!s}")
        import traceback
        traceback.print_exc()


async def test_chat_stream():
    """测试流式聊天"""
    print("\n" + "=" * 60)
    print("测试 2: 流式聊天")
    print("=" * 60)

    try:
        provider = get_provider()

        messages = [
            {"role": "user", "content": "请用三句话介绍一下人工智能"}
        ]

        print("发送消息：请用三句话介绍一下人工智能")
        print("流式响应:\n")
        print("-" * 60)

        # 收集完整响应
        full_content = ""

        async for chunk in provider.chat_completion_stream(
            messages=messages,
            temperature=0.7,
            max_tokens=200
        ):
            if chunk.content:
                print(chunk.content, end="", flush=True)
                full_content += chunk.content

            if chunk.is_final:
                print()
                print("-" * 60)
                print(f"\n完成原因: {chunk.finish_reason}")

        print()
        print(f"✅ 流式测试成功！共接收 {len(full_content)} 个字符")

    except Exception as e:
        print(f"❌ 测试失败: {e!s}")
        import traceback
        traceback.print_exc()


async def test_health_check():
    """测试健康检查"""
    print("\n" + "=" * 60)
    print("测试 3: 健康检查")
    print("=" * 60)

    try:
        provider = get_provider()
        is_healthy = await provider.health_check()

        if is_healthy:
            print("✅ 硅基流动服务健康检查通过")
        else:
            print("❌ 硅基流动服务健康检查失败")

    except Exception as e:
        print(f"❌ 健康检查失败: {e!s}")


async def main():
    """主测试函数"""
    print("\n🚀 开始测试硅基流动 AI 功能\n")

    # 检查配置
    print("📝 当前配置:")
    print(f"  - AI 功能已启用: {ai_config.enabled}")
    print(f"  - 默认 Provider: {ai_config.default_provider}")
    print(f"  - Base URL: {ai_config.openai.base_url}")
    print(f"  - 聊天模型: {ai_config.openai.chat_model}")
    print(f"  - API Key: {ai_config.openai.api_key[:20]}...")
    print()

    if not ai_config.enabled:
        print("❌ AI 功能未启用，请在 config/settings.toml 中设置 [ai] enabled = true")
        return

    if not ai_config.openai.api_key:
        print("❌ 未配置 API Key，请在 config/settings.toml 中设置 [ai.openai] api_key")
        return

    # 运行测试
    await test_chat_completion()
    await test_chat_stream()
    await test_health_check()

    print("\n" + "=" * 60)
    print("🎉 所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
