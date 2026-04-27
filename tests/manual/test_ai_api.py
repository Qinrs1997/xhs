#!/usr/bin/env python3
"""
测试 FastAPI 框架的 AI 接口

通过 HTTP 请求测试项目的 AI API 端点
"""
import asyncio
import httpx
import json


async def test_ai_chat_api():
    """测试聊天 API"""

    base_url = "http://localhost:8999"

    print("=" * 60)
    print("🧪 测试 FastAPI AI 接口")
    print("=" * 60)
    print()

    # 测试 1: 健康检查
    print("测试 1: 健康检查")
    print("-" * 60)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/health")

            if response.status_code == 200:
                print("✅ 服务健康检查通过")
                print(f"响应: {response.json()}")
            else:
                print(f"❌ 健康检查失败: {response.status_code}")
                return

    except Exception as e:
        print(f"❌ 无法连接到服务: {e}")
        print("\n请确保 FastAPI 服务已启动:")
        print("  cd /home/vision/projects/base_fastapi_ai")
        print("  ./scripts/start.sh")
        return

    print()

    # 测试 2: AI 聊天接口（普通模式）
    print("测试 2: AI 聊天接口（普通模式）")
    print("-" * 60)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            data = {
                "message": "你好，请用一句话介绍一下你自己",
                "stream": False
            }

            print(f"发送消息: {data['message']}")
            print("\n等待响应...\n")

            response = await client.post(
                f"{base_url}/api/v1/ai/chat",
                json=data
            )

            if response.status_code == 200:
                result = response.json()
                print("✅ 聊天请求成功！")
                print("-" * 60)
                print("响应内容:")
                print(result.get('content', result))
                print("-" * 60)

                if 'usage' in result:
                    print("\n📊 Token 使用情况:")
                    print(f"  - 输入 tokens: {result['usage'].get('prompt_tokens', 0)}")
                    print(f"  - 输出 tokens: {result['usage'].get('completion_tokens', 0)}")
                    print(f"  - 总计 tokens: {result['usage'].get('total_tokens', 0)}")
            else:
                print(f"❌ 请求失败: {response.status_code}")
                print(f"响应: {response.text}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    print()

    # 测试 3: AI 聊天接口（流式模式）
    print("测试 3: AI 聊天接口（流式模式）")
    print("-" * 60)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            data = {
                "message": "请用三句话介绍一下人工智能",
                "stream": True
            }

            print(f"发送消息: {data['message']}")
            print("\n流式响应:\n")
            print("-" * 60)

            full_content = ""

            async with client.stream(
                'POST',
                f"{base_url}/api/v1/ai/chat",
                json=data
            ) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            content = line[6:]  # 移除 'data: ' 前缀

                            if content.strip() == '[DONE]':
                                break

                            try:
                                chunk_data = json.loads(content)
                                if 'content' in chunk_data:
                                    text = chunk_data['content']
                                    print(text, end='', flush=True)
                                    full_content += text
                            except json.JSONDecodeError:
                                continue

                    print()
                    print("-" * 60)
                    print(f"\n✅ 流式测试成功！共接收 {len(full_content)} 个字符")
                else:
                    print(f"❌ 流式请求失败: {response.status_code}")
                    print(f"响应: {await response.aread()}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    print()
    print("=" * 60)
    print("🎉 测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_ai_chat_api())
