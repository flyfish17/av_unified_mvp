"""
modules/device_state/modbus_ac.py — 中央空调状态只读查询（Modbus RTU over TCP，USR-TCP232-304 网关）

协议事实源：creator_cc/docs/空调控制-协议记录.md（2026-08-18 现场实测）。
从机 0x32，功能码 03 读 4 寄存器：reg1=开关(0/1) reg2=模式 reg3=风速 reg4=温度(℃)。
本文件只做"读"（功能码 03），不含任何写帧；写在 creator_cc 的 live 开关后面。
"""
from __future__ import annotations

import socket

MODE = {0x02: "cool", 0x04: "heat", 0x08: "fan", 0x10: "dry"}
FAN = {0x08: "high", 0x04: "mid", 0x02: "low"}


def crc16(data: bytes) -> bytes:
    c = 0xFFFF
    for x in data:
        c ^= x
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c.to_bytes(2, "little")


def query_frame(base_reg: int, slave: int = 0x32) -> bytes:
    body = bytes([slave, 0x03]) + base_reg.to_bytes(2, "big") + (4).to_bytes(2, "big")
    return body + crc16(body)


def parse_reply(buf: bytes, slave: int = 0x32) -> dict:
    """回包 = slave 03 08 <8 字节 4 寄存器> CRC16。格式/CRC 不对直接抛错（不猜）。"""
    if len(buf) < 13:
        raise ValueError(f"回包不足 13 字节: {buf.hex()}")
    if buf[0] != slave or buf[1] != 0x03 or buf[2] != 0x08:
        raise ValueError(f"回包头异常: {buf[:3].hex()}")
    if crc16(buf[:11]) != buf[11:13]:
        raise ValueError(f"CRC 不符: {buf.hex()}")
    r = [int.from_bytes(buf[3 + 2 * i:5 + 2 * i], "big") for i in range(4)]
    return {
        "on": bool(r[0]),
        "mode": MODE.get(r[1], hex(r[1])),
        "fan": FAN.get(r[2], hex(r[2])),
        "temp": r[3],
    }


def read_ac(host: str, port: int, base_reg: int, timeout: float = 2.0) -> dict:
    """短连接读一台：连 → 发查询帧 → 收 13 字节 → 关。网关是 RS485 半双工，调用方要串行。"""
    req = query_frame(base_reg)
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(req)
        s.settimeout(timeout)
        buf = b""
        while len(buf) < 13:
            chunk = s.recv(64)
            if not chunk:
                break
            buf += chunk
    return parse_reply(buf)
