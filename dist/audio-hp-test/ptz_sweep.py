import fcntl, struct, time, subprocess, re
fd = open('/dev/hr8833','rb+',buffering=0)
FWD=0x40046d19; REV=0x40046d1a; STOP=0x40046d18
def io(c): return fcntl.ioctl(fd,c,struct.pack('i',0))
def ocp():
    try: return open('/sys/devices/platform/motor/ocp').read().strip()
    except: return '?'
def dbg(pat):
    """从 debugfs /sys/kernel/debug/gpio 抓 sleep/ain/ocp-det 行"""
    try:
        t=open('/sys/kernel/debug/gpio').read()
    except: return {}
    out={}
    for line in t.splitlines():
        for k in ('ain1','ain2','sleep','ocp-det'):
            if re.search(r'\|\s*'+k+r'\s*\(|\|\s*'+k+r'\s*\)', line):
                m=re.search(r'(out|in)\s+(hi|lo)', line)
                if m: out[k]=m.group(2)
    return out
# 时长扫描（ms）
durs=[20,40,60,80,100,120,160,200,240]
io(STOP); time.sleep(0.3)
print(f"STOP baseline: dbg={dbg('')} ocp={ocp()}")
print(f"{'dur_ms':>7} {'ocp@FWD':>8} {'nFAULT_fwd':>11} {'ocp_after':>10}")
for d in durs:
    io(STOP); time.sleep(0.25)
    ocp_before=ocp()
    io(FWD)
    # FWD 期间采样
    t0=time.time(); fwd_ocp=[]; fwd_nf=[]
    while (time.time()-t0)*1000 < d:
        fwd_ocp.append(ocp())
        g=dbg('')
        if 'ocp-det' in g: fwd_nf.append(g['ocp-det'])
        time.sleep(0.005)
    io(STOP); time.sleep(0.2)
    ocp_after=ocp()
    # FWD 期间 ocp 是否出现 1
    nf_fwd = 'LOW' if (fwd_nf and 'lo' in fwd_nf) else ('HIGH' if fwd_nf else '?')
    print(f"{d:7d} {'1' if '1' in fwd_ocp else '0':>8} {nf_fwd:>11} {ocp_after:>10}")
io(STOP)
print(f"final: dbg={dbg('')} ocp={ocp()}")
fd.close()
