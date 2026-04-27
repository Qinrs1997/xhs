"""Import the medicine carousel template from docs/templates into xhs_templates.

This script is intentionally idempotent: it updates the existing medicine
template with the same name/category, or creates it when missing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.xhs_template import XHSTemplate


PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "docs" / "模板" / "药品"
TARGET_SUBDIR = Path("xhs") / "templates" / "medicine"


def _load_template(source_dir: Path) -> dict[str, Any]:
    json_path = source_dir / "提示词.json"
    if not json_path.exists():
        raise FileNotFoundError(f"Template metadata not found: {json_path}")

    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _copy_asset(source_dir: Path, upload_dir: Path, file_name: str) -> str:
    source = source_dir / file_name
    if not source.exists():
        raise FileNotFoundError(f"Template asset not found: {source}")

    target_dir = upload_dir / TARGET_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)

    target_name = source.name
    target = target_dir / target_name
    shutil.copy2(source, target)

    url_base = f"/{settings.UPLOAD_DIR.rstrip('/')}/{TARGET_SUBDIR.as_posix()}"
    return f"{url_base}/{target_name}"


def _build_payload(source_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    upload_dir = Path(settings.UPLOAD_DIR)
    if not upload_dir.is_absolute():
        upload_dir = BACKEND_ROOT / upload_dir

    cover_url = _copy_asset(source_dir, upload_dir, metadata["overview_image_file"])

    example_pages: list[dict[str, Any]] = []
    for page in metadata.get("example_pages", []):
        page_data = dict(page)
        image_file = page_data.pop("example_image_file", None)
        if image_file:
            page_data["example_image_url"] = _copy_asset(
                source_dir, upload_dir, image_file
            )
        example_pages.append(page_data)

    return {
        "name": "药品科普卡片",
        "description": "四页式小红书药品科普模板，适合用法提醒、禁忌注意、误区说明和安全提示。",
        "category": metadata.get("category", "medicine"),
        "cover_url": cover_url,
        "default_topic": "阿莫西林用药指南",
        "style_prompt": metadata.get("style_prompt"),
        "content_prompt_template": metadata.get("content_prompt_template"),
        "page_count": int(metadata.get("page_count", 4)),
        "example_pages": example_pages,
        "is_new": True,
        "is_hot": True,
        "price": 0,
        "is_pro": False,
        "author_id": None,
        "tags": ["药品科普", "用药提醒", "健康", "安全用药", "4页模板"],
        "sort_order": 950,
        "is_active": True,
    }


async def import_template(source_dir: Path, dry_run: bool = False) -> int | None:
    metadata = _load_template(source_dir)
    payload = _build_payload(source_dir, metadata)

    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return None

    async with AsyncSessionLocal() as db:
        stmt = select(XHSTemplate).where(
            XHSTemplate.name == payload["name"],
            XHSTemplate.category == payload["category"],
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            print(f"Updated template id={existing.id}: {existing.name}")
            return existing.id

        template = XHSTemplate(**payload)
        db.add(template)
        await db.commit()
        await db.refresh(template)
        print(f"Created template id={template.id}: {template.name}")
        return template.id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import medicine XHS template")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing 提示词.json and template images",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload without writing to database",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(import_template(args.source_dir, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
