#!/usr/bin/env python3
"""RK3399-MID 触摸屏事件采集（无 evtest 环境用）

用法：
    python3 touchcap.py [秒数] [event 节点]
    python3 touchcap.py 20            # 采 20 秒 /dev/input/event2
    python3 touchcap.py 30 /dev/input/event2

判定方法（对照实验）：
    静置（无人触碰）应输出 0 事件 —— 证明控制器不虚报；
    人手滑屏应输出大量事件，TRACKING_ID 递增、坐标落在 ABS 范围内。
"""
import struct, sys, time, select, os

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
KEY = {0x14a: 'BTN_TOUCH', 0x145: 'BTN_TOOL_FINGER'}
ABS = {0x00: 'X', 0x01: 'Y', 0x2f: 'MT_SLOT', 0x35: 'MT_X', 0x36: 'MT_Y',
       0x39: 'TRACKING_ID', 0x3a: 'MT_PRESSURE', 0x37: 'MT_TOOL', 0x30: 'TOUCH_MAJOR'}

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
DEV = sys.argv[2] if len(sys.argv) > 2 else '/dev/input/event2'

fmt = 'llHHi'
sz = struct.calcsize(fmt)
fd = os.open(DEV, os.O_RDONLY | os.O_NONBLOCK)
t0 = time.time()
n = 0
mt = {}
slots = set()
ids = []
xmin = ymin = 10 ** 9
xmax = ymax = -1

while time.time() - t0 < DUR:
    r, _, _ = select.select([fd], [], [], 0.2)
    if not r:
        continue
    try:
        data = os.read(fd, sz * 64)
    except BlockingIOError:
        continue
    for i in range(0, len(data) - sz + 1, sz):
        s, us, typ, code, val = struct.unpack(fmt, data[i:i + sz])
        n += 1
        if typ == EV_KEY and code in KEY:
            print(f"[{time.time()-t0:6.2f}s] {KEY[code]} = {val}")
        elif typ == EV_ABS and code in ABS:
            mt[ABS[code]] = val
            if code == 0x2f:
                slots.add(val)
            if code == 0x39 and val >= 0:
                ids.append(val)
            if code in (0x35, 0x00):
                xmin, xmax = min(xmin, val), max(xmax, val)
            if code in (0x36, 0x01):
                ymin, ymax = min(ymin, val), max(ymax, val)
        elif typ == EV_SYN and code == 0 and ('MT_X' in mt or 'MT_Y' in mt):
            print(f"[{time.time()-t0:6.2f}s] MT slot={mt.get('MT_SLOT')} "
                  f"X={mt.get('MT_X')} Y={mt.get('MT_Y')} "
                  f"p={mt.get('MT_PRESSURE')} id={mt.get('TRACKING_ID')}")

os.close(fd)
print(f"--- total raw events: {n} in {DUR:.0f}s ---")
if n:
    print(f"--- slots seen: {sorted(slots)} ---")
    if ids:
        print(f"--- tracking ids: {len(set(ids))} unique, {min(ids)}..{max(ids)} ---")
    if xmax >= 0:
        print(f"--- X range {xmin}..{xmax}   Y range {ymin}..{ymax} ---")
