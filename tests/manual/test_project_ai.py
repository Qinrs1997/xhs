#!/usr/bin/env python3
"""
使用项目 AI 模块测试硅基流动

直接调用项目的 AI 模块，不需要启动完整的 FastAPI 服务
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 设置环境变量，跳过数据库
import os
os.environ['SKIP_DB'] = '1'


async def test_with_project_module():
    """使用项目模块测试"""

    print("=" * 60)
    print("🧪 使用项目 AI 模块测试硅基流动")
    print("=" * 60)
    print()

    try:
        # 导入配置
        from app.ai.config import ai_config
        from app.ai.providers import get_provider

        print("📝 当前配置:")
        print(f"  - AI 功能启用: {ai_config.enabled}")
        print(f"  - Provider: {ai_config.default_provider}")
        print(f"  - Base URL: {ai_config.openai.base_url}")
        print(f"  - 模型: {ai_config.openai.chat_model}")
        print(f"  - API Key: {ai_config.openai.api_key[:20]}...")
        print()

        if not ai_config.enabled:
            print("❌ AI 功能未启用")
            return

        # 获取 Provider
        provider = get_provider()
        print(f"✓ 获取到 Provider: {provider.name}")
        print()

        # 测试 1: 普通聊天
        print("测试 1: 普通聊天补全")
        print("-" * 60)

        messages = [
            {"role": "user", "content": "你好，请用一句话介绍一下你自己"}
        ]

        print(f"消息: {messages[0]['content']}")
        print("\n等待响应...\n")

        response = await provider.chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=100
        )

        print("✅ 请求成功！")
        print("-" * 60)
        print("响应内容:")
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

        # 测试 2: 流式聊天
        print("测试 2: 流式聊天")
        print("-" * 60)

        messages = [
            {"role": "user", "content": "请用三句话介绍一下人工智能"}
        ]

        print(f"消息: {messages[0]['content']}")
        print("\n流式响应:\n")
        print("-" * 60)

        full_content = ""

        async for chunk in provider.chat_completion_stream(
            messages=messages,
            temperature=0.7,
            max_tokens=200
        ):
            if chunk.content:
                print(chunk.content, end='', flush=True)
                full_content += chunk.content

            if chunk.is_final:
                print()
                print("-" * 60)
                print(f"\n完成原因: {chunk.finish_reason}")

        print()
        print(f"✅ 流式测试成功！共接收 {len(full_content)} 个字符")

        # 测试 3: 健康检查
        print()
        print("测试 3: 健康检查")
        print("-" * 60)

        is_healthy = await provider.health_check()

        if is_healthy:
            print("✅ 硅基流动服务健康检查通过")
        else:
            print("❌ 硅基流动服务健康检查失败")

        print()
        print("=" * 60)
        print("🎉 所有测试完成！硅基流动已成功对接到项目框架")
        print("=" * 60)
        print()
        print("📌 下一步:")
        print("  1. 确保数据库配置正确")
        print("  2. 运行 ./scripts/start.sh 启动完整服务")
        print("  3. 访问 http://localhost:8999/docs 查看 API 文档")
        print("  4. 调用 /api/v1/ai/chat 接口使用 AI 功能")

    except Exception as e:
        print(f"\n❌ 测试失败: {e!s}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_with_project_module())
