#!/usr/bin/env python3
"""
硅基流动 API 直接测试脚本

不依赖项目代码，直接通过 HTTP 请求测试硅基流动 API
"""
import asyncio
import json
import os


async def test_siliconflow_direct():
    """直接通过 HTTP 请求测试硅基流动 API"""

    # 配置 — 从环境变量读取，禁止硬编码
    api_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        print("❌ 请设置环境变量 SILICONFLOW_API_KEY")
        return
    base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.environ.get("SILICONFLOW_MODEL", "Qwen/Qwen3-8B")

    print("=" * 60)
    print("🚀 硅基流动 API 测试")
    print("=" * 60)
    print(f"API 地址: {base_url}")
    print(f"模型: {model}")
    print(f"API Key: {api_key[:20]}...")
    print()

    # 测试 1: 普通聊天
    print("测试 1: 普通聊天补全")
    print("-" * 60)

    try:
        # 使用 httpx
        try:
            import httpx
        except ImportError:
            print("❌ 需要安装 httpx: pip install httpx")
            return

        # 构建请求
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": model,
            "messages": [
                {"role": "user", "content": "你好，请用一句话介绍一下你自己"}
            ],
            "temperature": 0.7,
            "max_tokens": 100
        }

        print(f"发送请求到: {url}")
        print(f"消息: {data['messages'][0]['content']}")
        print("\n等待响应...\n")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()

                # 打印结果
                print("✅ 请求成功！")
                print("-" * 60)
                print("响应内容:")
                print(result['choices'][0]['message']['content'])
                print("-" * 60)
                print()
                print("📊 Token 使用情况:")
                usage = result.get('usage', {})
                print(f"  - 输入 tokens: {usage.get('prompt_tokens', 0)}")
                print(f"  - 输出 tokens: {usage.get('completion_tokens', 0)}")
                print(f"  - 总计 tokens: {usage.get('total_tokens', 0)}")
                print(f"  - 完成原因: {result['choices'][0].get('finish_reason', '')}")
                print(f"  - 模型: {result.get('model', '')}")
                print()

            else:
                print("❌ 请求失败！")
                print(f"状态码: {response.status_code}")
                print(f"响应: {response.text}")
                return

        # 测试 2: 流式输出
        print("\n" + "=" * 60)
        print("测试 2: 流式聊天")
        print("=" * 60)

        data['stream'] = True
        data['messages'] = [
            {"role": "user", "content": "请用三句话介绍一下人工智能"}
        ]

        print(f"消息: {data['messages'][0]['content']}")
        print("\n流式响应:\n")
        print("-" * 60)

        full_content = ""

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream('POST', url, headers=headers, json=data) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            content = line[6:]  # 移除 'data: ' 前缀

                            if content.strip() == '[DONE]':
                                break

                            try:
                                chunk_data = json.loads(content)
                                delta = chunk_data['choices'][0]['delta']

                                if 'content' in delta:
                                    text = delta['content']
                                    print(text, end='', flush=True)
                                    full_content += text

                            except json.JSONDecodeError:
                                continue

                    print()
                    print("-" * 60)
                    print(f"\n✅ 流式测试成功！共接收 {len(full_content)} 个字符")

                else:
                    print("❌ 流式请求失败！")
                    print(f"状态码: {response.status_code}")
                    print(f"响应: {await response.aread()}")

        print("\n" + "=" * 60)
        print("🎉 所有测试完成！硅基流动 API 工作正常")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e!s}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_siliconflow_direct())
