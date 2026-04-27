"""departments 子包内部共享工具"""

_TREE_CACHE_KEYS = ("dept_tree:True", "dept_tree:False")


async def invalidate_tree_cache() -> None:
    """清除部门树缓存（两种 include_inactive 变体）"""
    from app.core.cache import cache
    for key in _TREE_CACHE_KEYS:
        await cache.delete(key)
