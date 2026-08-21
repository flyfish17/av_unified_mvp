#!/usr/bin/env python3
"""
transcript_store.py
转写记录的追加式 JSONL 落盘存储（按天一个文件）。

事件只追加不回改，三种类型：
  {"type": "text",   "id": n, "time": "...", "text": "...", ...}   新转写
  {"type": "update", "id": n, "time": "...", <回填字段>}            classify 回填
  {"type": "alias",  "time": "...", "speaker_id": "S1", "name": "..."}  说话人改名
恢复时按行顺序重放即可重建内存列表；alias 重建 speaker_id→真名映射（name 空=撤销）。
"""
import json
import threading
from datetime import datetime
from pathlib import Path


class TranscriptStore:

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = None
        self._date = None
        self._next_id = 0
        self.aliases = {}  # speaker_id → 真名；load_today 重放恢复，archive 清空

    # ── 内部 ──────────────────────────────────────────────────────────

    @staticmethod
    def _today():
        return datetime.now().strftime("%Y-%m-%d")

    def _path_for(self, date_str):
        return self.base_dir / f"{date_str}.jsonl"

    def _write(self, obj):
        # 跨天时切到新文件；崩溃最多丢最后一条（每条写完即 flush）
        today = self._today()
        if self._fh is None or self._date != today:
            if self._fh:
                self._fh.close()
            self._date = today
            self._fh = open(self._path_for(today), "a", encoding="utf-8")
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._fh.flush()

    # ── 写入 ──────────────────────────────────────────────────────────

    def append_text(self, entry):
        """新转写创建时立即落盘，返回分配的事件 id。"""
        with self._lock:
            eid = self._next_id
            self._next_id += 1
            self._write({
                "type": "text",
                "id": eid,
                "time": entry.get("time"),
                "text": entry.get("text", ""),
                "is_command": entry.get("is_command", False),
                "cmd": entry.get("cmd"),
                "status": entry.get("status", "pending"),
                "segment_id": entry.get("segment_id", ""),
                "speaker_id": entry.get("speaker_id"),
                "speaker_confidence": entry.get("speaker_confidence"),
                # 3588 线补充：会议主机话筒身份（Mac 线无此路径）
                "mic_id": entry.get("mic_id"),
                "physical_id": entry.get("physical_id"),
            })
            return eid

    def append_update(self, eid, fields):
        """classify 回填结果时追加 update 事件，不回改已写行。"""
        with self._lock:
            self._write({
                "type": "update",
                "id": eid,
                "time": datetime.now().strftime("%H:%M:%S"),
                **fields,
            })

    def append_alias(self, speaker_id, name):
        """说话人改名落盘并更新映射；name 空串=撤销改名（回落 S# 显示）。"""
        with self._lock:
            if name:
                self.aliases[speaker_id] = name
            else:
                self.aliases.pop(speaker_id, None)
            self._write({
                "type": "alias",
                "time": datetime.now().strftime("%H:%M:%S"),
                "speaker_id": speaker_id,
                "name": name or "",
            })

    # ── 恢复 / 导出 / 归档 ────────────────────────────────────────────

    def load_today(self):
        """重放当天 jsonl，返回重建的 entries 列表（各条含 id 字段）。"""
        with self._lock:
            path = self._path_for(self._today())
            entries, by_id = [], {}
            max_id = -1
            self.aliases = {}
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue  # 崩溃残留的半行
                        eid = ev.get("id")
                        if ev.get("type") == "text":
                            entry = {
                                "id": eid,
                                "time": ev.get("time"),
                                "text": ev.get("text", ""),
                                "is_command": ev.get("is_command", False),
                                "cmd": ev.get("cmd"),
                                "status": ev.get("status", "pending"),
                                "segment_id": ev.get("segment_id", ""),
                                "speaker_id": ev.get("speaker_id"),
                                "speaker_confidence": ev.get("speaker_confidence"),
                            }
                            entries.append(entry)
                            by_id[eid] = entry
                            if isinstance(eid, int):
                                max_id = max(max_id, eid)
                        elif ev.get("type") == "update" and eid in by_id:
                            for k, v in ev.items():
                                if k not in ("type", "id", "time"):
                                    by_id[eid][k] = v
                        elif ev.get("type") == "alias" and ev.get("speaker_id"):
                            if ev.get("name"):
                                self.aliases[ev["speaker_id"]] = ev["name"]
                            else:
                                self.aliases.pop(ev["speaker_id"], None)
            self._next_id = max_id + 1
            return entries

    def export_today(self, export_dir):
        """从磁盘重放当天记录，写出固定名 txt（同名覆盖），返回导出路径。"""
        entries = self.load_today()
        lines = []
        for e in entries:
            tag = "[指令]" if e.get("is_command") else "[对话]"
            spk_label = self.aliases.get(e.get("speaker_id"), e.get("speaker_id"))
            spk = f"[{spk_label}] " if spk_label else ""
            line = f"[{e['time']}] {tag} {spk}{e['text']}"
            if e.get("cmd"):
                line += f"\n  → {json.dumps(e['cmd'], ensure_ascii=False)}"
            lines.append(line)
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        out = export_dir / f"语意理解_{self._today()}.txt"
        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    def archive_today(self):
        """当天 jsonl 归档为 YYYY-MM-DD.closed-HHMMSS.jsonl，不物理删除数据。"""
        with self._lock:
            today = self._today()
            if self._fh:
                self._fh.close()
                self._fh = None
            self._date = None
            self._next_id = 0
            self.aliases = {}
            path = self._path_for(today)
            if path.exists() and path.stat().st_size > 0:
                stamp = datetime.now().strftime("%H%M%S")
                target = self.base_dir / f"{today}.closed-{stamp}.jsonl"
                path.rename(target)
                return target
            return None
