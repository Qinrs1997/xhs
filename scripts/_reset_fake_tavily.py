"""一次性脚本：清掉演示用的假 Tavily Key，把内存 ai_config.search.api_key 也置空。"""
from __future__ import annotations

import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.getcwd())

from sqlalchemy import create_engine, text

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
with engine.begin() as conn:
    conn.execute(
        text("UPDATE ai_providers SET api_key = '' WHERE service_type = 'search'")
    )
print("DB ai_providers.api_key (service_type=search) cleared.")
