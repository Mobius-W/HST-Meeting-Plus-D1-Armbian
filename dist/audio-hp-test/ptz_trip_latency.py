#!/usr/bin/env python3
"""HR8833 OCP-DET 跳闸延迟精确测量（12us 级采样）
判据用途：
  - 跳闸延迟 ~20us 量级 ⇒ 电感电流以 V/L 斜率爬升到 IOCP(2.5A)，符合"低阻/短路路径"
  - 若延迟随脉冲长度变化或有数百 us 抖动 ⇒ 另有机制（供电塌陷/比较器）
用法: python3 ptz_trip_latency.py [trials]
"""
import os, sys, time, fcntl, struct

FWD = 0x40046d19
REV = 0x40046d1a
STOP = 0x40046d18
OCP_PATH = "/sys/devices/platform/motor/ocp"

def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    motor = open("/dev/hr8833", "rb+", buffering=0)
    fd = os.open(OCP_PATH, os.O_RDONLY)

    def rd():
        return os.pread(fd, 16, 0)[:1]

    def sample_until(pred, limit):
        seq = []
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) < limit:
            v = rd()
            t = time.perf_counter()
            seq.append((t, v))
            if pred(v, seq):
                break
        return seq

    print("trials=%d  单次采样 ~12us" % trials)
    for direction, cmd in (("FWD", FWD), ("REV", REV)):
        lats = []
        for k in range(trials):
            # 确认静止基线
            base = rd()
            # 起跳：记录 ioctl 返回时刻
            t_cmd = time.perf_counter()
            fcntl.ioctl(motor, cmd, struct.pack("i", 0))
            t_ret = time.perf_counter()
            seq = sample_until(lambda v, s: v == b"1", 0.2)
            t_hit = seq[-1][0] if seq[-1][1] == b"1" else None
            # 保持 20ms 看是否有重试回高
            hold = sample_until(lambda v, s: False, 0.02)
            highs = sum(1 for _, v in hold if v == b"1")
            fcntl.ioctl(motor, STOP, struct.pack("i", 0))
            # 恢复时间
            rec = sample_until(lambda v, s: v == b"0", 0.2)
            t_rec = rec[-1][0] if rec[-1][1] == b"0" else None

            lat = (t_hit - t_ret) * 1e6 if t_hit else None
            ioc = (t_ret - t_cmd) * 1e6
            rec_ms = (t_rec - t_cmd) * 1e6 / 1000 if t_rec else None
            if lat is not None:
                lats.append(lat)
            print("  %s #%d  base=%s  ioctl=%.0fus  trip=%s  hold20ms_high=%d/%d  recover=%sms" % (
                direction, k + 1, base.decode().strip(),
                ioc,
                ("%.0f us" % lat) if lat is not None else "NO-TRIP",
                highs, len(hold), ("%.2f" % rec_ms) if rec_ms else "?"))

        if lats:
            print("  %s trip: n=%d min=%.0f avg=%.0f max=%.0f us" % (
                direction, len(lats), min(lats), sum(lats) / len(lats), max(lats)))
        time.sleep(0.3)
    return 0

if __name__ == "__main__":
    sys.exit(main())
