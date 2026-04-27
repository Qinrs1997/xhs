"""PEM 密钥格式化工具

支付宝 SDK 要求私钥 / 公钥必须是 PEM 格式带 BEGIN/END 包装。
允许用户在配置里填入去掉包装的裸字符串，这里补齐 header / footer。
"""


def format_private_key(key: str) -> str:
    """确保私钥是 PEM 格式"""
    key = key.strip()
    if not key:
        return key
    if "BEGIN" not in key:
        key = f"-----BEGIN RSA PRIVATE KEY-----\n{key}\n-----END RSA PRIVATE KEY-----"
    return key


def format_public_key(key: str) -> str:
    """确保公钥是 PEM 格式"""
    key = key.strip()
    if not key:
        return key
    if "BEGIN" not in key:
        key = f"-----BEGIN PUBLIC KEY-----\n{key}\n-----END PUBLIC KEY-----"
    return key
