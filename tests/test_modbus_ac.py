"""
device_state 空调只读协议测试（无 pytest，直接 python3 tests/test_modbus_ac.py）
- 查询帧与协议记录里的实测帧逐字节一致（4 台）
- 回包解析：构造 32 03 08 + 4 寄存器 + CRC，解出开关/模式/风速/温度
- 假 TCP 网关端到端 read_ac
"""
import socket, sys, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.device_state.modbus_ac import crc16, query_frame, parse_reply, read_ac

P=F=0
def check(name, got, exp):
    global P, F
    ok = got == exp; P += ok; F += (not ok)
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  got={got!r} exp={exp!r}"))

# ① 查询帧 = 协议记录实测帧
for base, hexs in [(0x9C5C,"32039C5C0004AF88"),(0x9CB7,"32039CB70004DFBC"),(0x9D12,"32039D120004CE63"),(0x9D6D,"32039D6D0004FFBB")]:
    check(f"查询帧 {hex(base)}", query_frame(base).hex().upper(), hexs)
# ② 回包解析（实测记录：开,温度 0x15=21℃；模式制冷 0x02，风速中 0x04）
body = bytes([0x32,0x03,0x08]) + (1).to_bytes(2,"big") + (2).to_bytes(2,"big") + (4).to_bytes(2,"big") + (0x15).to_bytes(2,"big")
rep = body + crc16(body)
check("回包解析", parse_reply(rep), {"on": True, "mode": "cool", "fan": "mid", "temp": 21})
bad = rep[:-1] + bytes([rep[-1] ^ 0xFF])
try: parse_reply(bad); check("CRC 错必须抛", False, True)
except ValueError: check("CRC 错必须抛", True, True)
# ③ 假网关端到端：按查询基址回不同状态
TABLE = {0x9C5C: (0,2,8,16), 0x9CB7: (1,4,2,26)}
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(4); port = srv.getsockname()[1]
def serve():
    for _ in range(2):
        c,_ = srv.accept(); req = c.recv(64)
        base = int.from_bytes(req[2:4],"big"); r = TABLE[base]
        b = bytes([0x32,0x03,0x08]) + b"".join(v.to_bytes(2,"big") for v in r)
        c.sendall(b + crc16(b)); c.close()
threading.Thread(target=serve, daemon=True).start()
check("假网关 餐桌=关/制冷/高/16", read_ac("127.0.0.1", port, 0x9C5C), {"on": False, "mode": "cool", "fan": "high", "temp": 16})
check("假网关 研发=开/制热/低/26", read_ac("127.0.0.1", port, 0x9CB7), {"on": True, "mode": "heat", "fan": "low", "temp": 26})
print(f"\n结果：{P} passed, {F} failed"); sys.exit(1 if F else 0)
