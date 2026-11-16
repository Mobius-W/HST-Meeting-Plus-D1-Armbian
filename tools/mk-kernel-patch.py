#!/usr/bin/env python3
"""把 kernel-modules/<name>/<name>.c 打包成 Armbian 可用的内核补丁。

Armbian 会把 armbian/userpatches/kernel/archive/<family>-<ver>/*.patch
按序 `git apply` 到内核源码树，所以这里生成标准 git 风格的 unified diff：
  - 新增 drivers/misc/<name>.c
  - 在 drivers/misc/Makefile 末尾追加 obj-y += <name>.o

Makefile 的 hunk 行号/内容取自真实的 linux-headers 包（同一次构建产物），
保证与应用目标逐字节一致，不会因 fuzz 失败。

用法：
  tools/mk-kernel-patch.py --headers /tmp/hdr/data/usr/src/linux-headers-6.18.63-current-rockchip64
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH_DIR = os.path.join(
    REPO, "armbian/userpatches/kernel/archive/rockchip64-6.18")


def unified_new_file(path, content):
    lines = content.splitlines()
    out = [
        f"diff --git a/{path} b/{path}",
        "new file mode 100644",
        "index 0000000000000000000000000000000000000000..0000000000000000000000000000000000000000",
        "--- /dev/null",
        f"+++ b/{path}",
        f"@@ -0,0 +1,{len(lines)} @@",
    ]
    out += ["+" + ln for ln in lines]
    return out


def unified_append(path, old_lines, add_lines, ctx=3):
    """在文件末尾追加若干行，生成一个 hunk。"""
    n = len(old_lines)
    start = max(1, n - ctx + 1)
    ctx_lines = old_lines[start - 1:]
    out = [
        f"diff --git a/{path} b/{path}",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -{start},{len(ctx_lines)} +{start},{len(ctx_lines) + len(add_lines)} @@",
    ]
    out += [" " + ln for ln in ctx_lines]
    out += ["+" + ln for ln in add_lines]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headers", required=True,
                    help="解包后的 linux-headers-<ver> 目录")
    ap.add_argument("--name", default="hr8833")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = os.path.join(REPO, "kernel-modules", args.name, args.name + ".c")
    if not os.path.exists(src):
        sys.exit(f"找不到 {src}")

    with open(src, encoding="utf-8") as f:
        code = f.read()

    mf_path = os.path.join(args.headers, "drivers/misc/Makefile")
    with open(mf_path, encoding="utf-8") as f:
        makefile = f.read().splitlines()

    if any(args.name in ln for ln in makefile):
        sys.exit("Makefile 里已经包含该驱动，无需重复打补丁")

    add = [
        "",
        "# rk3399-mid: 板级驱动（module 形式，说明见文件头注释）",
        f"obj-m\t\t\t\t+= {args.name}.o",
    ]

    patch = []
    patch += unified_new_file(f"drivers/misc/{args.name}.c", code)
    patch += unified_append("drivers/misc/Makefile", makefile, add)

    out = args.out or os.path.join(
        PATCH_DIR, f"0001-misc-add-{args.name}.patch")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(patch) + "\n")

    print(f"written {out}  ({len(patch)} 行)")
    # 用真实的 headers 树做 dry-run，确认能干净应用
    r = subprocess.run(["patch", "--dry-run", "-p1", "-d", args.headers,
                        "-i", os.path.abspath(out)],
                       capture_output=True, text=True)
    print("patch --dry-run:", "OK" if r.returncode == 0 else r.stdout + r.stderr)


if __name__ == "__main__":
    main()
