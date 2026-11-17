import struct
from aps2 import RELOCS, D, cstr, sym, BASE_DR, SYM_OFF, SYM_SZ, STR_OFF

relmap = {}
for ro, info, add, fl in RELOCS:
    relmap[ro] = (info & 0xff, info >> 8, add)


def rv(vma):
    t, si, add = relmap.get(vma, (None, None, None))
    base = BASE_DR if vma >= 0x19830 else 0x5000
    word = struct.unpack_from('<I', D, vma - base)[0] if 0 <= vma - base < len(D) else 0
    if t == 23:
        return word
    if t == 2:
        return (sym(si)[0] + word) & 0xffffffff
    if t == 21:
        return sym(si)[0]
    return word


def fmt_val(v):
    s = cstr(v)
    if s:
        return '"%s"' % s
    # signed interpret
    return str(v if v < 0x80000000 else v - 0x100000000)


all_syms = []
for i in range(SYM_SZ // 16):
    o = SYM_OFF + i * 16
    name, val, sz, info, other, shndx = struct.unpack_from('<IIIBBH', D, o)
    e = D.find(b'\x00', STR_OFF + name)
    nm = D[STR_OFF + name:e].decode('utf8', 'replace')
    all_syms.append((nm, val, sz, shndx))

# control arrays: shndx==18 (.data.rel.ro), size multiple of 16 and >=16
# and first word resolves to a control-name string
ctrl_arrays = []
for nm, val, sz, shndx in all_syms:
    if shndx != 18 or sz < 16 or sz % 16:
        continue
    first = rv(val)
    if cstr(first):
        ctrl_arrays.append((nm, val, sz))

print('control arrays with string first field: %d' % len(ctrl_arrays))
for nm, val, sz in sorted(ctrl_arrays):
    n = sz // 16
    print('\n### %s  @0x%x  (%d controls)' % (nm, val, n))
    for k in range(n):
        a = val + k * 16
        name = rv(a)
        f1, f2, f3 = rv(a + 4), rv(a + 8), rv(a + 12)
        print('  [%d] %-30s | f1=%-14s | f2=%-8s | f3=%s' % (
            k, fmt_val(name), fmt_val(f1), fmt_val(f2), fmt_val(f3)))
