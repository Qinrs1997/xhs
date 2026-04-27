import requests
import json

BASE_URL = "http://127.0.0.1:8999/api/v1"

def login():
    print("正在尝试登录获取 Token...")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login-token",
            data={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            print("登录成功！")
            return token
        else:
            print(f"登录失败: {response.text}")
            return None
    except Exception as e:
        print(f"登录出错: {e}")
        return None

def test_generic_image(token):
    print("\n测试通用图像生成接口...")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "prompt": "极简主义风格的日落山脉，柔和的色彩",
        "size": "1024x1024",
        "n": 1
    }

    try:
        response = requests.post(
            f"{BASE_URL}/ai/image/generate",
            json=payload,
            headers=headers,
            timeout=120
        )
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"生成的图片 URL: {data['images'][0]['url']}")
        else:
            print(f"错误: {response.text}")
    except Exception as e:
        print(f"请求异常: {e}")

def test_xhs_image_stream(token):
    print("\n测试小红书流式图像生成接口...")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "pages": [
            {
                "index": 1,
                "title": "封面页",
                "content": "这是一张绝美的封面",
                "image_prompt": "A beautiful landscape cover for Xiaohongshu",
                "page_type": "cover"
            },
            {
                "index": 2,
                "title": "内容页",
                "content": "内容详情",
                "image_prompt": "Detailed product close up",
                "page_type": "content"
            }
        ],
        "outline": "测试大纲",
        "user_topic": "测试主题"
    }

    try:
        response = requests.post(
            f"{BASE_URL}/xhs/image/stream",
            json=payload,
            headers=headers,
            stream=True,
            timeout=300
        )
        print(f"状态码: {response.status_code}")

        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data: "):
                    data = json.loads(decoded_line[6:])
                    print(f"事件: {data}")
    except Exception as e:
        print(f"请求异常: {e}")

if __name__ == "__main__":
    token = login()
    if token:
        # 注意：实际运行可能需要有效的 AI API Key，否则会返回 500/503
        test_generic_image(token)
        test_xhs_image_stream(token)
    else:
        print("未获取到 Token，取消测试")
