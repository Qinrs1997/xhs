"""邮箱验证码服务

提供验证码生成、存储、校验能力。
用于注册邮箱验证、登录二次验证等场景。
"""
import random
import time
import string
from typing import Optional

from app.core.logger import logger


class VerifyCodeStore:
    """
    验证码内存存储（带 TTL）

    结构: {email: {"code": str, "expire": float, "attempts": int}}

    安全措施:
    - 验证码 5 分钟过期
    - 同一邮箱 60 秒内不可重复发送
    - 同一 IP 每分钟最多发送 3 次（防批量攻击）
    - 验证失败 5 次后自动失效
    - 验证成功后立即删除（一次性）
    """

    _store: dict[str, dict] = {}
    _ip_counter: dict[str, list[float]] = {}  # {ip: [timestamp1, timestamp2, ...]}

    CODE_LENGTH = 6                  # 验证码位数
    CODE_TTL = 300                   # 有效期（秒）= 5 分钟
    RESEND_INTERVAL = 60             # 重发间隔（秒）= 60 秒
    MAX_VERIFY_ATTEMPTS = 5          # 最大验证尝试次数
    IP_RATE_LIMIT = 3                # 同一 IP 每分钟最多发送次数
    IP_RATE_WINDOW = 60              # IP 限流窗口（秒）

    @classmethod
    def check_ip_rate(cls, client_ip: str) -> Optional[str]:
        """
        检查 IP 发送频率

        Args:
            client_ip: 客户端 IP

        Returns:
            None 表示通过，str 表示错误信息
        """
        if not client_ip:
            return None

        now = time.time()
        timestamps = cls._ip_counter.get(client_ip, [])

        # 清理过期的时间戳
        timestamps = [t for t in timestamps if now - t < cls.IP_RATE_WINDOW]
        cls._ip_counter[client_ip] = timestamps

        if len(timestamps) >= cls.IP_RATE_LIMIT:
            return "操作太频繁，请稍后再试"

        return None

    @classmethod
    def record_ip_send(cls, client_ip: str) -> None:
        """记录 IP 发送"""
        if not client_ip:
            return
        now = time.time()
        cls._ip_counter.setdefault(client_ip, []).append(now)

    @classmethod
    def generate(cls, email: str, client_ip: str = "") -> tuple[str, Optional[str]]:
        """
        生成验证码

        Args:
            email: 邮箱地址
            client_ip: 客户端 IP（用于 IP 限流）

        Returns:
            (code, error) - 成功返回 (验证码, None)，失败返回 ("", 错误信息)
        """
        email = email.lower().strip()
        now = time.time()

        # 检查 IP 限流
        ip_error = cls.check_ip_rate(client_ip)
        if ip_error:
            return "", ip_error

        # 检查重发间隔
        existing = cls._store.get(email)
        if existing:
            created_at = existing.get("created_at", 0)
            elapsed = now - created_at
            if elapsed < cls.RESEND_INTERVAL:
                remaining = int(cls.RESEND_INTERVAL - elapsed)
                return "", f"发送太频繁，请 {remaining} 秒后重试"

        # 生成 6 位数字验证码
        code = "".join(random.choices(string.digits, k=cls.CODE_LENGTH))

        cls._store[email] = {
            "code": code,
            "expire": now + cls.CODE_TTL,
            "created_at": now,
            "attempts": 0,
        }

        # 记录 IP 发送
        cls.record_ip_send(client_ip)

        logger.info("验证码已生成: email={}, code={}", email, code)

        # 定期清理过期条目（简单策略：超过 1000 条时清理）
        if len(cls._store) > 1000:
            cls._cleanup()

        return code, None

    @classmethod
    def verify(cls, email: str, code: str) -> tuple[bool, Optional[str]]:
        """
        校验验证码

        Args:
            email: 邮箱地址
            code: 用户输入的验证码

        Returns:
            (success, error) - 成功返回 (True, None)，失败返回 (False, 错误信息)
        """
        email = email.lower().strip()
        code = code.strip()
        now = time.time()

        record = cls._store.get(email)
        if not record:
            return False, "验证码不存在或已过期，请重新获取"

        # 检查过期
        if now > record["expire"]:
            cls._store.pop(email, None)
            return False, "验证码已过期，请重新获取"

        # 检查尝试次数
        if record["attempts"] >= cls.MAX_VERIFY_ATTEMPTS:
            cls._store.pop(email, None)
            return False, "验证码错误次数过多，请重新获取"

        # 校验
        if record["code"] != code:
            record["attempts"] += 1
            remaining = cls.MAX_VERIFY_ATTEMPTS - record["attempts"]
            return False, f"验证码错误，还可尝试 {remaining} 次"

        # 验证成功，立即删除（一次性使用）
        cls._store.pop(email, None)
        return True, None

    @classmethod
    def _cleanup(cls):
        """清理过期条目"""
        now = time.time()
        expired_keys = [k for k, v in cls._store.items() if now > v["expire"]]
        for k in expired_keys:
            cls._store.pop(k, None)
        # 清理 IP 计数器
        expired_ips = [ip for ip, ts in cls._ip_counter.items()
                       if all(now - t >= cls.IP_RATE_WINDOW for t in ts)]
        for ip in expired_ips:
            cls._ip_counter.pop(ip, None)
        if expired_keys:
            logger.debug("清理了 {} 个过期验证码", len(expired_keys))


# 全局实例
verify_code_store = VerifyCodeStore()

