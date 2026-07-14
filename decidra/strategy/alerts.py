"""策略告警：jsonl 落盘、增量读取与信号去重状态。

告警经 ``alerts.jsonl`` 追加写传递给 monitor（与 cron 基础设施相同的文件通信
模式）；去重状态按 (symbol, strategy, action) 记录已告警的 K 线时间，
同一根 K 线只告警一次。

并发安全：写路径（append_alerts / DedupeState.save / save_enrichment）统一经
openharness 的 exclusive_file_lock + atomic_write_text 序列化（cron 触发的
runner 与 monitor 内工具可能并发读写同一份文件）；读路径无需加锁——jsonl 为
追加写，JSON 状态文件为原子替换。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text

from ..utils.global_vars import PATH_STRATEGY_RUNTIME

RUNTIME_DIR: Path = PATH_STRATEGY_RUNTIME
ALERTS_PATH: Path = RUNTIME_DIR / "alerts.jsonl"
DEDUPE_STATE_PATH: Path = RUNTIME_DIR / "dedupe_state.json"
ENRICHMENTS_PATH: Path = RUNTIME_DIR / "enrichments.json"

# read_recent_alerts 尾部回退读取的块大小
_TAIL_CHUNK_BYTES = 64 * 1024


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


@dataclass
class Alert:
    """一条策略告警。"""

    dt: str                # 告警产生时间（ISO）
    symbol: str
    strategy: str
    action: str            # BUY / SELL
    reason: str
    bar_dt: str            # 触发信号的 K 线时间（ISO，去重锚点）
    snapshot: Dict[str, Any] = field(default_factory=dict)
    # 短码 id，供终端展示与人工引用（如"研判 #a1b2c3d4"）
    id: str = field(default_factory=lambda: uuid4().hex[:8])


def append_alerts(alerts: List[Alert], path: Path = ALERTS_PATH) -> None:
    """追加告警到 jsonl 文件（锁内单次写入）。"""
    if not alerts:
        return
    payload = "".join(json.dumps(asdict(a), ensure_ascii=False) + "\n" for a in alerts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(_lock_path(path)):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(payload)


def _parse_jsonl(text: str) -> List[dict]:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def read_new_alerts(offset: int, path: Path = ALERTS_PATH) -> Tuple[List[dict], int]:
    """从字节偏移 ``offset`` 起读取新增告警，返回 (告警列表, 新偏移)。

    偏移只推进到最后一个完整换行处：并发写入者尚未写完的半行留待下轮，
    不会被跳过丢失。文件不存在返回 ([], 0)；文件被截断时从头重读。
    """
    if not path.exists():
        return [], 0
    size = path.stat().st_size
    if offset > size:
        offset = 0
    if offset == size:
        return [], offset

    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read()

    last_newline = chunk.rfind(b"\n")
    if last_newline < 0:
        # 只有半行，等待写入者完成
        return [], offset
    complete = chunk[: last_newline + 1]
    new_offset = offset + last_newline + 1
    return _parse_jsonl(complete.decode("utf-8", errors="replace")), new_offset


def read_recent_alerts(n: int = 5, path: Path = ALERTS_PATH) -> List[dict]:
    """读取最近 n 条告警（尾部按块回退读取，不加载整个文件）。"""
    if n <= 0 or not path.exists():
        return []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
        buf = b""
        # 多回退一行余量：pos>0 时首段可能是半行需丢弃
        while pos > 0 and buf.count(b"\n") <= n:
            step = min(_TAIL_CHUNK_BYTES, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
    if pos > 0:
        # 未读到文件头：丢弃可能不完整的首段
        buf = buf.split(b"\n", 1)[1] if b"\n" in buf else b""
    records = _parse_jsonl(buf.decode("utf-8", errors="replace"))
    return records[-n:]


def find_alert(alert_id: str, path: Optional[Path] = None) -> Optional[dict]:
    """按短码 id 查找告警（多条同 id 时取最后一条，找不到返回 None）。"""
    path = path or ALERTS_PATH
    if not alert_id or not path.exists():
        return None
    found = None
    for alert in _parse_jsonl(path.read_text(encoding="utf-8")):
        if alert.get("id") == alert_id:
            found = alert
    return found


def load_enrichments(path: Optional[Path] = None) -> Dict[str, dict]:
    """读取全部研判结论（alert_id → enrichment），文件不存在返回空字典。"""
    path = path or ENRICHMENTS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_enrichment(alert_id: str, enrichment: dict, path: Optional[Path] = None) -> None:
    """写入/覆盖一条告警的研判结论（锁内读-改-写 + 原子替换）。"""
    path = path or ENRICHMENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(_lock_path(path)):
        data = load_enrichments(path)
        data[alert_id] = enrichment
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


class DedupeState:
    """信号去重状态：(symbol, strategy, action) → 已告警的 bar_dt。"""

    def __init__(self, path: Path = DEDUPE_STATE_PATH):
        self.path = path
        self._state = self._load(path)

    @staticmethod
    def _load(path: Path) -> Dict[str, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except json.JSONDecodeError:
            data = {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def key(symbol: str, strategy: str, action: str) -> str:
        return f"{symbol}|{strategy}|{action}"

    def should_fire(self, symbol: str, strategy: str, action: str, bar_dt: str) -> bool:
        """同一 (symbol, strategy, action) 在同一根 K 线上只告警一次。"""
        return self._state.get(self.key(symbol, strategy, action)) != bar_dt

    def mark(self, symbol: str, strategy: str, action: str, bar_dt: str) -> None:
        self._state[self.key(symbol, strategy, action)] = bar_dt

    def save(self) -> None:
        """锁内合并盘上最新状态后原子写回（并发扫描互不丢更新）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(_lock_path(self.path)):
            merged = self._load(self.path)
            merged.update(self._state)
            atomic_write_text(
                self.path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
            )
