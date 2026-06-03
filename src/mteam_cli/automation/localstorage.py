"""LocalStorage manager — load/save a page's localStorage to a JSON file.

Ported verbatim from the original ``LocalStorageManager``. M-Team's
SPA keeps its auth token in localStorage, so persisting/restoring it is what
lets subsequent logins skip the password+TOTP step.
"""

from __future__ import annotations

import json
import logging

from playwright.async_api import Error as PlaywrightError, Page

logger = logging.getLogger("mteam_cli.automation")


class LocalStorageManager:
    def __init__(self, page: Page) -> None:
        self.page = page

    async def set_value(self, key: str, value: str) -> None:
        escaped_value = json.dumps(value)
        await self.page.evaluate(f'localStorage.setItem("{key}", {escaped_value})')

    async def save_to_file(self, filename: str) -> None:
        storage_data = await self.page.evaluate("() => JSON.stringify(localStorage)")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(json.loads(storage_data), f, ensure_ascii=False, indent=4)

    async def load_from_file(self, filename: str) -> None:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                storage_data = json.load(f)
            for key, value in storage_data.items():
                try:
                    await self.set_value(key, value)
                except (PlaywrightError, ValueError) as e:
                    logger.error("设置键 '%s' 的值时出错: %s", key, str(e))
        except FileNotFoundError:
            logger.warning("文件 %s 不存在，无法加载 LocalStorage 数据。", filename)
        except json.JSONDecodeError:
            logger.error("文件 %s 不是有效 JSON，无法加载 LocalStorage 数据。", filename)
        except IOError as e:
            logger.error("读取文件 %s 时发生 I/O 错误: %s", filename, str(e))
