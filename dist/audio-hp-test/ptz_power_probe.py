import fcntl, struct, time
fd = open('/dev/hr8833','rb+',buffering=0)
FWD=0x40046d19; REV=0x40046d1a; STOP=0x40046d18
def io(c): return fcntl.ioctl(fd,c,struct.pack('i',0))
OCP='/sys/devices/platform/motor/ocp'
def ocp():
    try: return open(OCP).read().strip()
    except: return '?'
def gpio(g):
    try: return open(f'/sys/class/gpio/gpio{g}/value').read().strip()
    except: return '?'
# gpio2=ain1, gpio3=ain2, gpio4=sleep(nSLEEP,ACTIVE_LOW), gpio5=ocp-det(nFAULT,ACTIVE_LOW)
print(f"BEFORE: ain1={gpio(2)} ain2={gpio(3)} nSLEEP={gpio(4)}(1=phys hi=wake) nFAULT={gpio(5)}(1=phys hi=OK) ocp={ocp()}")
io(STOP); time.sleep(0.1)
# 发 FWD 1.2s，期间每 8ms 采样 nFAULT/ocp，看是否被拉低（=有电流=上电导通）
print("--- FWD 1.2s, 采样 nFAULT(gpio5)/ocp 每8ms ---")
io(FWD)
seq=[]; t0=time.time()
while time.time()-t0 < 1.2:
    seq.append((round(time.time()-t0,2), gpio(5), ocp()))
    time.sleep(0.008)
io(STOP)
time.sleep(0.2)
# 统计
vals=[s[1] for s in seq]
print(f"samples={len(seq)} nFAULT_phys_lo_count={vals.count('0')} nFAULT_phys_hi_count={vals.count('1')}")
# 打印状态转折点
prev=None
for t,nf,oc in seq:
    if nf!=prev:
        print(f"  t={t:.2f}s nFAULT_phys={nf} {'(LOW=FAULT/过流=有电流)' if nf=='0' else '(HIGH=OK)'} ocp={oc}")
        prev=nf
print(f"AFTER: ain1={gpio(2)} ain2={gpio(3)} nSLEEP={gpio(4)} nFAULT={gpio(5)} ocp={ocp()}")
fd.close()
