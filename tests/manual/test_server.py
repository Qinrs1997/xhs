#!/usr/bin/env python3
import requests
import time

print("测试 FastAPI 服务...")

# 等待服务启动
time.sleep(2)

# 测试健康检查
print("\n1. 测试健康检查...")
try:
    response = requests.get("http://localhost:8999/health", timeout=5)
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.text}")
except Exception as e:
    print(f"错误: {e}")

# 测试登录
print("\n2. 测试登录...")
try:
    response = requests.post(
        "http://localhost:8999/api/v1/auth/login-token",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=5
    )
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.text}")
except Exception as e:
    print(f"错误: {e}")
