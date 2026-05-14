#!/usr/bin/env python3
"""
modules/web_browser/main.py
浏览器模块（POC 框架） — Playwright 自动化各品牌 web 后台。

sub: av/web_browser/cmd  {action: screenshot|click|type|goto, target, params}
pub: av/web_browser/state {action, target, ok, screenshot_b64, extract, error}
config["web_browser"]: {dry_run: true, targets: {<name>: {url, login: {...}}}}
默认 dry_run=True：只 log 不真启 chromium。

---
husion HDC900 专用接入 (5/14 Sub-C 中午 POC 验证)
- 后台地址: http://192.168.5.253/  (nginx + Vue.js + ElementUI, title "可视化综合管理系统")
- 登录: POST /api/login {username, password(密文), isadmin, issso, role, is_admin, is_sso}
       密码 admin/123456 经浏览器内 JS 加密成 "aR7eWESkeD5swJMLDjQN4w=="，可直接重放
       返回 JWT，后续请求 Authorization: Bearer <jwt>
- 9 设备 (id 5001-5009): GET /api/get_all_equ → name/ip/dev_type/hls(ws flv 流地址)
                       GET /api/get_all_display → 含 wall + RX 输出端
- 视频墙状态: GET /api/wall/w?wall_id=1 → 当前墙上窗口 + tx_id 映射
- 视频墙详情: GET /api/wall/wall_details?idWall=1 → 分辨率/RX 列表/preset
- 视频源切换 (从 JS 扫到, 未实测): POST /api/wall/switch, /api/wall/buildWin, /api/wall/editWin
- xpanel-browser 设备列表 (空, 用于另一套设备注册): /api/xpanel_browser/devices/list
- JS 共扫到 256 个 /api/ endpoint, 已落 /tmp/husion_all_apis.json
"""
import asyncio
import base64
import json
import logging
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule  # noqa: E402

CMD_TOPIC = "av/web_browser/cmd"
STATE_TOPIC = "av/web_browser/state"

# ---- husion HDC900 REST 接入常量 ----
HUSION_BASE = "http://192.168.5.253"
HUSION_LOGIN_PAYLOAD = {
    # 注意: password 是 admin/123456 在 husion 前端 JS 里加密后的密文
    # 5/14 Sub-C 抓包验证可直接重放; 如要支持其他账号需逆向 JS 加密函数
    "username": "admin",
    "password": "aR7eWESkeD5swJMLDjQN4w==",
    "isadmin": True,
    "issso": True,
    "role": "admin",
    "is_admin": True,
    "is_sso": True,
}


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

    # ============================================================
    # husion HDC900 REST 专用 handler (5/14 Sub-C 中午验证)
    # 跑通了 login + 9 设备列表 + 墙状态查询的直 REST 调用
    # 视频源切换 endpoint 已定位 (未实操点击, 避免影响 husion 现场状态)
    # ============================================================

    def _husion_login(self) -> str:
        """登录 husion + 返回 JWT token。

        密码字段是 admin/123456 在前端 JS 里加密后的密文 (已固化为常量, 可直接重放)。
        Returns: JWT token string
        Raises: HTTPError / JSONDecodeError 等
        """
        req = urllib.request.Request(
            f"{HUSION_BASE}/api/login",
            data=json.dumps(HUSION_LOGIN_PAYLOAD).encode(),
            headers={"Content-Type": "application/json;charset=UTF-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        return data["data"]["token"]

    def _husion_get(self, path: str, token: str) -> dict:
        req = urllib.request.Request(
            f"{HUSION_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    def _husion_list_devices(self, token: str | None = None) -> list[dict]:
        """读 9 路设备状态 (id 5001-5009 + 墙 id=1)。

        返回每项含: id / name / ip / dev_type / online / hls(ws flv 拉流地址)
        """
        if token is None:
            token = self._husion_login()
        resp = self._husion_get("/api/get_all_equ", token)
        return resp.get("data") or []

    def _husion_get_wall_state(self, wall_id: int = 1, token: str | None = None) -> dict:
        """查视频墙当前状态 (墙上有几个窗口, 每个窗口显示哪个 tx_id)。

        Returns: {"windows": [...], "details": {...}}
        """
        if token is None:
            token = self._husion_login()
        windows = self._husion_get(f"/api/wall/w?wall_id={wall_id}", token).get("data") or []
        details = self._husion_get(f"/api/wall/wall_details?idWall={wall_id}", token).get("data") or {}
        return {"windows": windows, "details": details}

    def _husion_switch_scene(self, rx_id: int | str, scene_name: str, token: str | None = None) -> dict:
        """切换 RX 显示器到指定预编排场景（5/14 user 实操 XHR 抓取后接入）。

        Args:
            rx_id: RX 显示器设备 ID（如 5008 对应"输出至 CR 分布式"显示端）
            scene_name: husion 后台预编排好的场景名（如"单屏" / "四分屏" / 客户自定义）
            token: 可选 JWT；不传则自动登录

        Returns: husion 完整响应 dict
          {statusCode, code, message, data: [{rxid, scenename, audio, hdmi, mode, switchList}]}
          - mode: "1x1" / "2x2" / "3x3" 等布局模式
          - switchList: [{win, name, hls, txid}] 每个 win 实际播的信号源

        实测路径（5/14 13:09 user 抓 XHR 确认）：
          GET /api/wall/rx_scene?wall_id={rx_id}&scene={scene_name URL-encoded}
          切"单屏": wall_id=5008&scene=%E5%8D%95%E5%B1%8F
          切"四分屏": wall_id=5008&scene=%E5%9B%9B%E5%88%86%E5%B1%8F

        ⚠️ 前提: 场景必须先在 husion 后台 web "预编排" 模式手动定义好。
        我们只触发"切到已定义场景"，不动态新建窗口（避免脏 husion 配置）。
        """
        import urllib.parse
        if token is None:
            token = self._husion_login()
        scene_enc = urllib.parse.quote(str(scene_name))
        path = f"/api/wall/rx_scene?wall_id={rx_id}&scene={scene_enc}"
        return self._husion_get(path, token)

    # 旧名向后兼容（5/14 Sub-3 写的占位接口）
    def _husion_switch_source(self, wall_id, win_id, tx_id, token=None):
        """已废弃 — 真实 husion 协议是按"场景"切换，不是按 win/tx 切。
        请改用 _husion_switch_scene(rx_id, scene_name)。
        """
        raise NotImplementedError(
            "husion 切换协议实际按预编排场景名切，不是 win/tx 三元组。"
            "请用 _husion_switch_scene(rx_id, scene_name)，参考 docstring。"
        )


def main() -> None:
    import yaml

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    cfg_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    WebBrowserModule(cfg).run()


if __name__ == "__main__":
    main()
