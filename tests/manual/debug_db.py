#!/usr/bin/env python3
"""详细的数据库连接调试"""
import pymysql

print("PyMySQL 版本1:", pymysql.__version__)
print()

# 配置
config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': 'qin123123',
    'database': 'dsp',
    'charset': 'utf8mb4'
}

print("尝试 1: 基本连接")
print("-" * 60)
try:
    conn = pymysql.connect(**config)
    print("✅ 连接成功！")
    conn.close()
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n尝试 2: 指定 127.0.0.1")
print("-" * 60)
config['host'] = '127.0.0.1'
try:
    conn = pymysql.connect(**config)
    print("✅ 连接成功！")
    conn.close()
except Exception as e:
    print(f"❌ 失败: {e}")

print("\n尝试 3: 不指定数据库")
print("-" * 60)
config_no_db = config.copy()
del config_no_db['database']
try:
    conn = pymysql.connect(**config_no_db)
    print("✅ 连接成功！")
    with conn.cursor() as cursor:
        cursor.execute("SHOW DATABASES")
        print("数据库列表:", [row[0] for row in cursor.fetchall()])
    conn.close()
except Exception as e:
    print(f"❌ 失败: {e}")

print("\n尝试 4: 添加超时设置")
print("-" * 60)
config['connect_timeout'] = 30
config['read_timeout'] = 30
config['write_timeout'] = 30
try:
    conn = pymysql.connect(**config)
    print("✅ 连接成功！")
    conn.close()
except Exception as e:
    print(f"❌ 失败: {e}")

print("\n尝试 5: 检查 MySQL 配置")
print("-" * 60)
import subprocess
result = subprocess.run(
    ['mysql', '-u', 'root', '-pqin123123', '-e', 'SELECT @@max_allowed_packet, @@max_connections, @@wait_timeout;'],
    capture_output=True,
    text=True
)
print(result.stdout)
if result.returncode != 0:
    print("stderr:", result.stderr)
