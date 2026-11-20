import fcntl, struct, time, re
fd = open('/dev/hr8833','rb+',buffering=0)
FWD=0x40046d19; STOP=0x40046d18
def io(c): return fcntl.ioctl(fd,c,struct.pack('i',0))
def nfault_phys():
    """返回 ocp-det 物理电平 hi/lo，从 debugfs 抓"""
    try: t=open('/sys/kernel/debug/gpio').read()
    except: return '?'
    for line in t.splitlines():
        if 'ocp-det' in line:
            m=re.search(r'in\s+(hi|lo)', line)
            if m: return m.group(1)
    return '?'
def sleepv():
    try: t=open('/sys/kernel/debug/gpio').read()
    except: return '?'
    for line in t.splitlines():
        if re.search(r'\|\s*sleep', line):
            m=re.search(r'out\s+(hi|lo)', line)
            if m: return m.group(1)
    return '?'
io(STOP); time.sleep(0.3)
print(f"baseline: sleep_phys={sleepv()} (hi=work) nFAULT_phys={nfault_phys()} (hi=OK)")
# 测 FWD→nFAULT 拉低延迟，多次测量
for trial in range(5):
    io(STOP); time.sleep(0.15)
    # 先确认起始 hi
    if nfault_phys()!= 'hi': 
        print(f"  trial{trial}: pre not hi, skip"); continue
    t_start=time.perf_counter()
    io(FWD)
    t_fault=None
    # 高频轮询 debugfs 抓首次 lo（注意 debugfs 读取开销 ~几十us）
    while time.perf_counter()-t_start < 0.3:
        if nfault_phys()=='lo':
            t_fault=time.perf_counter()-t_start
            break
    io(STOP)
    # 释放后恢复时间
    t_r=time.perf_counter(); rec=None
    while time.perf_counter()-t_r < 0.5:
        if nfault_phys()=='hi': rec=time.perf_counter()-t_r; break
        time.sleep(0.001)
    print(f"  trial{trial}: FWD→nFAULT_LOW = {t_fault*1000:.2f}ms  | release→recover = {rec*1000 if rec else 'NA'}ms")
print(f"final: nFAULT_phys={nfault_phys()} ocp={open('/sys/devices/platform/motor/ocp').read().strip()}")
fd.close()
