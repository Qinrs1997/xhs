"""批量为 xhs_templates 生成真实封面图并回写 cover_url。

典型场景:
- 新模板入库时 cover_url 为空,前端回退成渐变色块 + emoji,商业化体验差
- 老模板需要批量换封面风格

用法:
    # 只处理 cover_url 为空的模板（默认）
    python scripts/generate_template_covers.py

    # 指定几个 id
    python scripts/generate_template_covers.py --ids 1 2 3

    # 全部覆盖（危险: 会重算所有模板的封面）
    python scripts/generate_template_covers.py --overwrite

    # 仅 dry-run 打印 prompt 不生图
    python scripts/generate_template_covers.py --dry-run

前置:
- .env 中 AI_API_KEY 必须是真实有效的图模 API Key (默认跑 ai_config 默认图模)
- UPLOAD_DIR 可写（默认 ./uploads）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import httpx

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.getcwd())


async def _main(ids: list[int] | None, overwrite: bool, dry_run: bool) -> int:
    from sqlalchemy import select, update

    from app.ai.facade import ai
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.xhs_template import XHSTemplate

    Session = AsyncSessionLocal

    upload_dir = Path(settings.UPLOAD_DIR) / "xhs" / "templates"
    upload_dir.mkdir(parents=True, exist_ok=True)
    url_base = f"/{settings.UPLOAD_DIR.rstrip('/')}/xhs/templates"

    # 1) 找目标行
    async with Session() as db:
        stmt = select(XHSTemplate).where(XHSTemplate.is_active.is_(True))
        if ids:
            stmt = stmt.where(XHSTemplate.id.in_(ids))
        elif not overwrite:
            stmt = stmt.where(
                (XHSTemplate.cover_url.is_(None)) | (XHSTemplate.cover_url == "")
            )
        rows = (await db.execute(stmt.order_by(XHSTemplate.id.asc()))).scalars().all()

    print(f"[cover-gen] matched {len(rows)} templates")
    if dry_run:
        for t in rows:
            print(f"  id={t.id} name={t.name} style_prompt={t.style_prompt or '-'}")
        return 0

    if not rows:
        return 0

    async def _handle_one(tpl: XHSTemplate) -> Optional[str]:
        # 构造封面 prompt: 模板名 + 风格提示词 + 主题关键词
        parts: list[str] = []
        if tpl.style_prompt:
            parts.append(tpl.style_prompt.strip())
        parts.append(
            f"小红书封面，主题：{tpl.name}。要点：{tpl.default_topic or tpl.name}"
        )
        parts.append("竖版 9:16 构图, 明亮干净, 中央留白适合加大字标题, 商业可用")
        prompt = "\n".join(parts)

        resp = await ai.image_generate(
            prompt=prompt, size="1024x1792", n=1
        )
        images = getattr(resp, "images", None) or []
        if not images:
            raise RuntimeError("image model returned no image")

        img_url = getattr(images[0], "url", None) or images[0].get("url")
        if not img_url:
            raise RuntimeError("image url missing in response")

        # 下载到本地
        filename = f"cover_{tpl.id}_{uuid.uuid4().hex[:8]}.png"
        save_path = upload_dir / filename
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(img_url)
            r.raise_for_status()
            save_path.write_bytes(r.content)

        web_url = f"{url_base}/{filename}".replace("//", "/")
        return web_url

    success = 0
    async with Session() as db:
        for tpl in rows:
            try:
                new_url = await _handle_one(tpl)
                if not new_url:
                    continue
                await db.execute(
                    update(XHSTemplate)
                    .where(XHSTemplate.id == tpl.id)
                    .values(cover_url=new_url)
                )
                await db.commit()
                print(f"  [OK]  id={tpl.id} -> {new_url}")
                success += 1
            except Exception as e:
                print(f"  [FAIL] id={tpl.id}: {e}")
    print(f"[cover-gen] done, success {success}/{len(rows)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="批量为 xhs_templates 生成真实封面图"
    )
    parser.add_argument("--ids", type=int, nargs="*", help="仅处理这些模板 id")
    parser.add_argument(
        "--overwrite", action="store_true", help="覆盖已有 cover_url"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅打印不生图")
    args = parser.parse_args()
    return asyncio.run(
        _main(args.ids, args.overwrite, args.dry_run)
    )


if __name__ == "__main__":
    sys.exit(main())
