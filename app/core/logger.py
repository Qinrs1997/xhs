"""统一日志模块 (loguru 版)

提供全局 logger 实例，支持：
- 控制台彩色输出（开箱即用）
- 按天生成独立日志文件（自动切割 + 自动压缩 + 自动清理）
- 请求 ID / 用户 ID 自动注入
- 错误日志独立存储

使用方法：
    from app.core.logger import logger
    logger.info("消息")
    logger.error("错误信息")

迁移说明：
    - 对外接口完全不变：`from app.core.logger import logger, get_logger`
    - 所有 `logger.info/debug/warning/error` 调用无需任何修改
    - loguru 的 logger 是全局单例，`get_logger(name)` 通过 bind 实现模块标识
"""
import sys
import logging
from pathlib import Path

from loguru import logger as _loguru_logger

from app.core.config import settings


def _request_context_patcher(record):
    """为日志记录注入请求上下文（request_id, user_id）"""
    try:
        from app.core.context import get_request_id, get_current_user_id
        request_id = get_request_id()
        user_id = get_current_user_id()
    except Exception:
        request_id = None
        user_id = None

    record["extra"].setdefault("request_id", request_id[:8] if request_id else "-")
    record["extra"].setdefault("user_id", str(user_id) if user_id else "-")


def setup_logger():
    """
    配置 loguru 日志系统

    对外导出的 logger 与 stdlib logging.Logger 接口兼容：
    - logger.info / debug / warning / error / critical
    - logger.exception（自动附带 traceback）
    """
    # 移除 loguru 默认 handler（避免重复输出）
    _loguru_logger.remove()

    # 注入请求上下文
    _loguru_logger.configure(patcher=_request_context_patcher)

    log_level = settings.LOG_LEVEL.upper()
    log_dir = Path(settings.LOG_FILE).parent if settings.LOG_FILE else Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 控制台输出（带颜色） ====================
    _loguru_logger.add(
        sys.stdout,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<dim>[{extra[request_id]}]</dim> "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
        colorize=True,
        backtrace=True,
        diagnose=settings.DEBUG,  # 仅 DEBUG 模式显示变量详情
    )

    # ==================== 日志文件（按天切割） ====================
    _loguru_logger.add(
        str(log_dir / "app_{time:YYYY-MM-DD}.log"),
        level=log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} [{extra[request_id]}] [user:{extra[user_id]}] "
            "{level:<8} | {name}:{line} | {message}"
        ),
        rotation="00:00",                              # 每天午夜切割
        retention=f"{settings.LOG_BACKUP_COUNT} days",  # 保留天数
        compression="gz",                               # 自动压缩旧日志
        encoding="utf-8",
        enqueue=True,                                   # 异步写入，不阻塞事件循环
    )

    # ==================== 错误日志（独立文件） ====================
    _loguru_logger.add(
        str(log_dir / "error_{time:YYYY-MM-DD}.log"),
        level="ERROR",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} [{extra[request_id]}] [user:{extra[user_id]}] "
            "{level:<8} | {name}:{line} | {message}\n{exception}"
        ),
        rotation="00:00",
        retention=f"{settings.LOG_BACKUP_COUNT} days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,  # 错误日志始终显示详细诊断
    )

    # ==================== 拦截 stdlib logging → loguru ====================
    # 让使用 stdlib logging 的第三方库（SQLAlchemy, uvicorn 等）
    # 也通过 loguru 统一输出
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            # 获取对应的 loguru 级别
            try:
                level = _loguru_logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # 查找调用者帧
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    # 拦截所有 stdlib logger
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    return _loguru_logger


# 初始化并导出全局 logger
logger = setup_logger()


def get_logger(name: str):
    """
    获取带模块名称的 logger 实例

    Args:
        name: 模块名称，建议使用 __name__

    Returns:
        绑定了模块名的 loguru logger

    使用方法：
        from app.core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("模块消息")
    """
    return logger.bind(module=name)
