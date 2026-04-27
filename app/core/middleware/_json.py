"""中间件共享 JSON 编解码工具

优先使用 orjson（C 扩展，比 stdlib json 快 5-10 倍）；
orjson 为可选依赖，不可用时回退到 stdlib json。
"""
try:
    import orjson

    def json_loads(data: bytes) -> dict:
        return orjson.loads(data)

    def json_dumps(data: dict) -> bytes:
        return orjson.dumps(data, option=orjson.OPT_NON_STR_KEYS)

except ImportError:
    import json

    def json_loads(data: bytes) -> dict:  # type: ignore[misc]
        return json.loads(data)

    def json_dumps(data: dict) -> bytes:  # type: ignore[misc]
        return json.dumps(data, ensure_ascii=False).encode("utf-8")
