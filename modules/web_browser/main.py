#!/usr/bin/env python3
"""
modules/web_browser/main.py
浏览器模块（POC 框架） — Playwright 自动化各品牌 web 后台。

sub: av/web_browser/cmd  {action: screenshot|click|type|goto, target, params}
pub: av/web_browser/state {action, target, ok, screenshot_b64, extract, error}
config["web_browser"]: {dry_run: true, targets: {<name>: {url, login: {...}}}}
默认 dry_run=True：只 log 不真启 chromium。
"""
import asyncio
import base64
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule  # noqa: E402

CMD_TOPIC = "av/web_browser/cmd"
STATE_TOPIC = "av/web_browser/state"


class WebBrowserModule(BaseModule):
    """Playwright 浏览器自动化模块（dry-run 默认）。"""

    def __init__(self, config: dict):
        super().__init__("web_browser", config)
        wb_cfg = config.get("web_browser", {}) or {}
        self.dry_run: bool = bool(wb_cfg.get("dry_run", True))
        self.targets: dict = wb_cfg.get("targets", {}) or {}
        self.screenshot_dir = Path(wb_cfg.get("screenshot_dir", "/tmp/web_browser_shots"))
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.subscribe(CMD_TOPIC, qos=1)

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic != CMD_TOPIC:
            return
        action = (payload.get("action") or "").lower()
        target = payload.get("target")
        params = payload.get("params") or {}
        self.logger.info(f"cmd action={action} target={target} dry_run={self.dry_run}")
        if self.dry_run:
            self._reply(action, target, ok=True, extract={"dry_run": True}); return
        tgt_cfg = self.targets.get(target)
        if not tgt_cfg:
            self._reply(action, target, ok=False, error=f"unknown target: {target}"); return
        try:
            result = asyncio.run(self._run(action, tgt_cfg, params))
            self._reply(action, target, ok=True, **result)
        except Exception as e:
            self.logger.exception("playwright 执行失败")
            self._reply(action, target, ok=False, error=f"{type(e).__name__}: {e}")

    async def _run(self, action: str, tgt_cfg: dict, params: dict) -> dict:
        # 延迟 import：dry-run 模式下不强依赖 playwright
        from playwright.async_api import async_playwright

        url = tgt_cfg["url"]
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1366, "height": 900})
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                if action in ("type", "click"):
                    sel = params["selector"]
                    if action == "type":
                        await page.fill(sel, params.get("text", ""))
                    else:
                        await page.click(sel)
                # 默认始终截图（screenshot / click / type / goto）
                shot_path = self.screenshot_dir / f"{tgt_cfg.get('name','t')}_{int(asyncio.get_event_loop().time())}.png"
                await page.screenshot(path=str(shot_path), full_page=True)
                with open(shot_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                title = await page.title()
                return {"screenshot_b64": b64, "screenshot_path": str(shot_path), "extract": {"title": title}}
            finally:
                await ctx.close()
                await browser.close()

    def _reply(self, action: str, target: str, ok: bool, **kw) -> None:
        self.publish(STATE_TOPIC, {"action": action, "target": target, "ok": ok, **kw}, qos=1)


def main() -> None:
    import yaml

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    cfg_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    WebBrowserModule(cfg).run()


if __name__ == "__main__":
    main()
