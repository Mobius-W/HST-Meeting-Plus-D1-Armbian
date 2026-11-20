#!/usr/bin/env python3
"""接管 HR8833 全部控制引脚（需先 rmmod hr8833），判定 OCP-DET 到底是谁的信号。
关键判据：nSLEEP=低（睡眠）时 H 桥被禁止、nFAULT 应为高阻释放；
  若此时 OCP-DET 仍被拉低 ⇒ 它不是芯片 nFAULT，而是板级检测电路。
矩阵：
  coast  A1=0 A2=0  nSLEEP=1   无电流，应无故障
  brake  A1=1 A2=1  nSLEEP=1   上下桥臂同时导通，静态无电流，应无故障
  fwd    A1=1 A2=0  nSLEEP=1   有电流，预期故障
  rev    A1=0 A2=1  nSLEEP=1
  sleep  A1=1 A2=0  nSLEEP=0   桥禁用 —— 决定性
"""
import ctypes, fcntl, os, struct, sys, time

IOC = lambda nr, size: (3 << 30) | (size << 16) | (0xB4 << 8) | nr
GET_HANDLE = IOC(0x0B, 364)
SET_VALUES = IOC(0x09, 64)
GET_VALUES = IOC(0x08, 64)
FLAG_INPUT = 1
FLAG_OUTPUT = 2
CHIP = "/dev/gpiochip2"
L_AIN1, L_AIN2, L_SLEEP, L_OCP = 2, 3, 4, 5

def req(lines, flags, label):
    buf = bytearray(364)
    for i, ln in enumerate(lines):
        struct.pack_into("I", buf, i * 4, ln)
    struct.pack_into("I", buf, 256, flags)
    if flags == FLAG_OUTPUT:
        for i in range(len(lines)):
            buf[260 + i] = 0
    buf[324:356] = label.encode()[:31].ljust(32, b"\x00")  # 必须整 32 字节，否则 bytearray 会被截短
    struct.pack_into("I", buf, 356, len(lines))
    struct.pack_into("i", buf, 360, 0)
    fd_chip = os.open(CHIP, os.O_RDWR)
    try:
        fcntl.ioctl(fd_chip, GET_HANDLE, buf, True)
    finally:
        os.close(fd_chip)
    return struct.unpack_from("i", buf, 360)[0]

def set_vals(fd, vals):
    data = bytearray(64)
    for i, v in enumerate(vals):
        data[i] = v
    fcntl.ioctl(fd, SET_VALUES, data, True)

def get_val(fd):
    data = bytearray(64)
    fcntl.ioctl(fd, GET_VALUES, data, True)
    return data[0]

def main():
    try:
        fo = req([L_AIN1, L_AIN2, L_SLEEP], FLAG_OUTPUT, "ptz-diag")
        fi = req([L_OCP], FLAG_INPUT, "ptz-diag")
    except OSError as e:
        print("引脚申请失败（模块可能未卸载）:", e)
        return 1

    def phase(name, ain1, ain2, nsleep, ms=30):
        set_vals(fo, [ain1, ain2, nsleep])
        t0 = time.perf_counter()
        n = low = 0
        first_low = None
        while (time.perf_counter() - t0) * 1000 < ms:
            v = get_val(fi)
            n += 1
            if v == 1:  # 物理低 = 拉低
                low += 1
                if first_low is None:
                    first_low = (time.perf_counter() - t0) * 1e6
        print("  %-6s A1=%d A2=%d nSLEEP=%d  n=%d  low=%d (%.1f%%)  first_low=%s" % (
            name, ain1, ain2, nsleep, n, low, 100.0 * low / max(1, n),
            ("%.0fus" % first_low) if first_low is not None else "-"))

    print("== OCP-DET 归属判定（物理电平：1=被拉低=故障） ==")
    phase("coast", 0, 0, 1)
    phase("brake", 1, 1, 1)
    phase("fwd",   1, 0, 1)
    phase("rev",   0, 1, 1)
    phase("sleep", 1, 0, 0)   # 桥禁用
    phase("sleep2", 1, 1, 0)
    set_vals(fo, [0, 0, 1])
    return 0

if __name__ == "__main__":
    sys.exit(main())
