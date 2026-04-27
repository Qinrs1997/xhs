#!/usr/bin/env python3
"""测试数据库连接"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

import pymysql
from sqlalchemy import create_engine, text

# 配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': 'qin123123',
    'database': 'dsp',
    'charset': 'utf8mb4'
}

print("=" * 60)
print("测试 1: PyMySQL 直接连接")
print("=" * 60)

try:
    conn = pymysql.connect(**DB_CONFIG)
    print("✅ PyMySQL 连接成功")

    with conn.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        print(f"MySQL 版本: {version[0]}")

    conn.close()
    print("✅ 连接关闭成功\n")

except Exception as e:
    print(f"❌ PyMySQL 连接失败: {e}\n")

print("=" * 60)
print("测试 2: SQLAlchemy 同步引擎")
print("=" * 60)

try:
    # 构建 SQLAlchemy 连接字符串
    url = f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}?charset={DB_CONFIG['charset']}"

    # 创建引擎（不使用连接池）
    engine = create_engine(
        url,
        poolclass=None,  # 不使用连接池
        echo=False
    )

    print(f"引擎创建成功: {engine}")

    # 测试连接
    with engine.connect() as conn:
        result = conn.execute(text("SELECT VERSION()"))
        version = result.scalar()
        print("✅ SQLAlchemy 连接成功")
        print(f"MySQL 版本: {version}")

    engine.dispose()
    print("✅ 引擎关闭成功\n")

except Exception as e:
    print(f"❌ SQLAlchemy 连接失败: {e}")
    import traceback
    traceback.print_exc()
    print()

print("=" * 60)
print("测试 3: SQLAlchemy 带连接池")
print("=" * 60)

try:
    # 使用项目配置
    from app.core.config import settings

    print("数据库配置:")
    print(f"  Host: {settings.DB_HOST}")
    print(f"  Port: {settings.DB_PORT}")
    print(f"  Database: {settings.DB_NAME}")
    print(f"  User: {settings.DB_USER}")
    print(f"  Pool Size: {settings.DB_POOL_SIZE}")
    print(f"  Max Overflow: {settings.DB_MAX_OVERFLOW}")
    print(f"  Pool Timeout: {settings.DB_POOL_TIMEOUT}")
    print(f"  Pool Recycle: {settings.DB_POOL_RECYCLE}")
    print()

    # 使用项目的数据库引擎
    from app.core.database import sync_engine

    print(f"使用项目引擎: {sync_engine}")

    # 测试连接
    with sync_engine.connect() as conn:
        result = conn.execute(text("SELECT VERSION()"))
        version = result.scalar()
        print("✅ 项目数据库连接成功")
        print(f"MySQL 版本: {version}")

    print("✅ 测试完成\n")

except Exception as e:
    print(f"❌ 项目数据库连接失败: {e}")
    import traceback
    traceback.print_exc()
    print()

print("=" * 60)
print("🎯 诊断完成")
print("=" * 60)
