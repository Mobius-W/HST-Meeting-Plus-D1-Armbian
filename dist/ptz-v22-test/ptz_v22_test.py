#!/usr/bin/env python3
# hr8833 v2.2 定位语义上板测试矩阵（在 D1 / rk3399-mid 上运行）
# 前置：rmmod hr8833; insmod /root/hr8833-v22/hr8833.ko
# 板级 AOUT 短路存在时：所有"转"的动作预期立即跳 OCP 并被状态机 coast。
import fcntl, os, struct, sys, time

DEV = "/dev/hr8833"
IOC = lambda d, t, nr, sz: (d << 30) | (sz << 16) | (ord(t) << 8) | nr
TURN  = IOC(1, "H", 6, 4)          # _IOW('H',6,s32)
GOTO  = IOC(1, "H", 7, 4)          # _IOW('H',7,s32)
GETPOS= IOC(2, "H", 8, 8)          # _IOR('H',8,struct{int;int})
GETOCP= IOC(2, "H", 5, 4)          # _IOR('H',5,int)
STOP  = IOC(0, "H", 2, 0)          # _IO('H',2)
V_END = 0x40046D18; V_FWD = 0x40046D19; V_REV = 0x40046D1A

fd = os.open(DEV, os.O_RDWR)

def wioctl(cmd, data=b""):
    return fcntl.ioctl(fd, cmd, data)      # OSError on negative retval

def rioctl(cmd, size):
    b = bytearray(size)
    fcntl.ioctl(fd, cmd, b, True)          # by-reference, result in b
    return bytes(b)

def turn(deg, cmd=TURN):
    try:
        wioctl(cmd, struct.pack("<i", deg))
        return 0
    except OSError as e:
        return -e.errno

def pos():
    deg, valid = struct.unpack("<ii", rioctl(GETPOS, 8))
    return (deg, valid)

SYS = "/sys/devices/platform/motor"
def rd(name):
    for p in (f"{SYS}/{name}", f"/sys/devices/virtual/misc/hr8833/hr8833/{name}",
              f"/sys/module/hr8833/parameters/{name}"):
        try:
            return open(p).read().strip()
        except OSError:
            pass
    return "<n/a>"

def sec(t): time.sleep(t)

print("== 0. 基线 ==")
print("position:", pos(), " ocp:", rd("ocp"), " sleep:", rd("sleep_state"))
print("fault_state:", rd("fault_state"))
print("irq_stat:", rd("irq_stat").replace("\n", " | "))

print("\n== 1. TURN +10°（预期 0=接受，随即 OCP coast） ==")
print("ret:", turn(10))
sec(1.0)
print("position:", pos(), " ocp:", rd("ocp"), " fault:", rd("fault_state"))

print("\n== 2. 冷却期内再转（预期 -EAGAIN=-11） ==")
print("ret:", turn(10))

print("\n== 3. 冷却 300ms 后循环转 5 次（预期第 5 次后 fault latched） ==")
for i in range(5):
    sec(0.3)
    r = turn(10)
    sec(0.3)
    print(f"  turn#{i+1}: ret={r} fault={rd('fault_state')}")
print("此时 TURN（预期 -EIO=-5）:", turn(10))

print("\n== 4. position_reset（预期清零并解锁） ==")
os.system(f"echo 1 > {SYS}/position_reset")
print("position:", pos(), " fault:", rd("fault_state"))

print("\n== 5. vendor 0x19/0x18 回归（不切 nSLEEP；0x19 期间 position 变 invalid） ==")
wioctl(V_FWD); sec(0.3); wioctl(V_END); sec(0.2)
print("position:", pos(), " ocp:", rd("ocp"), " sleep:", rd("sleep_state"), " fault:", rd("fault_state"))

print("\n== 6. GOTO（position 已 invalid，预期 -ENODATA=-77；reset 后可 GOTO） ==")
print("ret:", turn(30, GOTO))
os.system(f"echo 1 > {SYS}/position_reset")
print("reset 后 GOTO 30:", turn(30, GOTO)); sec(0.5)
print("position:", pos(), " fault:", rd("fault_state"))

print("\n== 7. 收尾：STOP + 统计 ==")
wioctl(STOP)
print("irq_stat:", rd("irq_stat").replace("\n", " | "))
print("dmesg tail:")
os.system("dmesg | grep -iE 'hr8833|OCP' | tail -12")
