"""Thao tác với nhịp độ của người thật: gõ có độ trễ, nghỉ ngẫu nhiên giữa các bước."""
from __future__ import annotations

import asyncio
import random


async def pause(a: float = 0.4, b: float = 1.2):
    await asyncio.sleep(random.uniform(a, b))


async def type_into(page, locator, text: str):
    await locator.click()
    await pause(0.2, 0.5)
    # xóa nội dung cũ
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")
    if len(text) > 400:
        # prompt dài: dán một lần như người dùng copy-paste
        await locator.fill(text) if await _is_fillable(locator) else await page.keyboard.insert_text(text)
    else:
        await page.keyboard.type(text, delay=random.randint(8, 25))
    await pause(0.3, 0.8)


async def _is_fillable(locator) -> bool:
    try:
        tag = await locator.evaluate("e => e.tagName")
        return tag in ("TEXTAREA", "INPUT")
    except Exception:
        return False
