#!/usr/bin/env python3
"""
在设备上直接给 rk3399-mid.dtb 加「麦阵复合 codec」节点（免重编内核的快速验证路径）

做的事：
  1. 给 i2c1 下的 es7243@10 / es7243@12 补 phandle
  2. 在根节点加 mic-array 节点（compatible = rockchip,rk3399-mid-audio）
  3. 把 es7148-sound 的 codec sound-dai 从 audio-dac 改指向 mic-array

用法：
  dtc -I dtb -O dts -o /tmp/cur.dts /boot/dtb/rockchip/rk3399-mid.dtb
  python3 patch_dtb.py /tmp/cur.dts /tmp/new.dts
  dtc -I dts -O dtb -o /tmp/new.dtb /tmp/new.dts
"""
import re
import sys

PH_MIC = 0x1F0
PH_ADC12 = 0x1F1
PH_ADC10 = 0x1F2


def find_block_end(text, start):
    """从 start（指向 '{' 之后）找到配对的 '}' 的下标（含）。"""
    depth = 1
    i = start
    while i < len(text) and depth:
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        i += 1
    return i  # 指向 '}' 之后


def add_phandle(text, node_header, phandle):
    """在 node_header 指向的块里补一行 phandle。"""
    idx = text.index(node_header)
    brace = text.index('{', idx)
    end = find_block_end(text, brace + 1)
    body = text[brace + 1:end]
    if 'phandle' in body:
        return text
    indent = '\t\t\t'
    ins = f'{indent}phandle = <0x{phandle:x}>;\n'
    pos = brace + 1
    return text[:pos] + '\n' + ins + text[pos:]


def main(src, dst):
    text = open(src).read()

    # cru（clock-controller@ff760000）的 phandle，mic-array 要用它引用 SCLK_I2S_8CH_OUT
    mc = re.search(r'clock-controller@ff760000 \{[^}]*?phandle = <(0x[0-9a-f]+)>;',
                   text, re.S)
    if not mc:
        sys.exit('cru (clock-controller@ff760000) phandle 没找到')
    ph_cru = mc.group(1)

    # ---- 幂等分支：mic-array 已存在（上一轮打过补丁）只补 clocks ----
    if 'mic-array {' in text:
        idx = text.index('mic-array {')
        brace = text.index('{', idx)
        end = find_block_end(text, brace + 1)
        body = text[brace + 1:end]
        if 'clock-names' in body:
            open(dst, 'w').write(text)
            print('already patched (mic-array with clocks), copied as-is')
            return
        ins = (f'\n\t\tclocks = <{ph_cru} 0x59>;\t/* SCLK_I2S_8CH_OUT = 89 */'
               f'\n\t\tclock-names = "mclk";')
        text = text[:brace + 1] + ins + text[brace + 1:]
        open(dst, 'w').write(text)
        print(f'added clocks=<{ph_cru} 0x59> to existing mic-array')
        return

    text = add_phandle(text, 'es7243@12 {', PH_ADC12)
    text = add_phandle(text, 'es7243@10 {', PH_ADC10)

    # 取出 es7148-sound -> codec -> sound-dai 的旧 phandle
    m = re.search(r'es7148-sound \{.*?simple-audio-card,codec \{\s*sound-dai = <(0x[0-9a-f]+)>;',
                  text, re.S)
    if not m:
        sys.exit('es7148-sound/codec/sound-dai 没找到')
    old = m.group(1)
    text = text[:m.start(1)] + f'0x{PH_MIC:x}' + text[m.end(1):]

    # cru（clock-controller@ff760000）的 phandle，mic-array 要用它引用 SCLK_I2S_8CH_OUT
    mc = re.search(r'clock-controller@ff760000 \{[^}]*?phandle = <(0x[0-9a-f]+)>;',
                   text, re.S)
    if not mc:
        sys.exit('cru (clock-controller@ff760000) phandle 没找到')
    ph_cru = mc.group(1)

    # 根节点里插 mic-array：放在 audio-dac 块之后
    anchor = 'audio-dac {'
    idx = text.index(anchor)
    brace = text.index('{', idx)
    end = find_block_end(text, brace + 1)
    # find_block_end 停在 '}' 之后，节点这里还差一个 ';'，插到分号之后
    end = text.index(';', end) + 1
    node = f"""
	mic-array {{
		compatible = "rockchip,rk3399-mid-audio";
		#sound-dai-cells = <0x00>;
		clocks = <{ph_cru} 0x59>;	/* SCLK_I2S_8CH_OUT = 89 */
		clock-names = "mclk";
		everest,adc = <0x{PH_ADC10:x} 0x{PH_ADC12:x}>;
		status = "okay";
		phandle = <0x{PH_MIC:x}>;
	}};
"""
    text = text[:end] + node + text[end:]

    open(dst, 'w').write(text)
    print(f'ok: codec sound-dai {old} -> 0x{PH_MIC:x}, '
          f'adc 0x10=<0x{PH_ADC10:x}> adc 0x12=<0x{PH_ADC12:x}>')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
