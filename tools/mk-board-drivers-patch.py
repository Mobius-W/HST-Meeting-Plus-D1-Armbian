#!/usr/bin/env python3
"""把 kernel-modules/{es7243,hr8833}/*.c 打包成单个 Armbian 内核补丁。

设计要点（修复 2026-11-17 CI 的 0001/0003 应用失败）：
  1. 新文件 patch 用 git apply 兼容的标准格式：diff --git + new file mode
     + --- /dev/null + +++ b/path，**不带全零 index 行**（全零 index 会让
     Armbian patching.py 的 patch 工具误判成 reverse、跳过新文件创建）。
     参照本来就成功的 0002-imx307.patch 的写法。
  2. 两个驱动合并进**一个** patch， drivers/misc/Makefile 只改一次，
     消除"两个 patch 抢同一 Makefile 同一位置、后者 hunk 失配"的问题。
  3. Makefile hunk 用**文件头部锚点**（@@ -1,4 +1,8 @@，SPDX 注释块），
     而不是尾部行号（尾部 @@ -75,3 会随内核小版本滚动失效）。头部 4 行
     在 linux-6.18.63/64 逐字节一致，稳定。

用法：
  tools/mk-board-drivers-patch.py --verify-root /tmp/kcheck/6.18.64
  （--verify-root 指向解包好的内核源码树，用于生成后立刻 dry-run 验证）
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH_DIR = os.path.join(REPO, "armbian/userpatches/kernel/archive/rockchip64-6.18")
OUT_NAME = "0001-misc-add-rk3399-drivers.patch"

DRIVERS = ["es7243", "hr8833"]


def new_file_hunk(path: str, content: str) -> list[str]:
    """标准 git 风格新文件 hunk，无 index 行（关键：避免 reverse 误判）。"""
    lines = content.splitlines()
    return [
        f"diff --git a/{path} b/{path}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{path}",
        f"@@ -0,0 +1,{len(lines)} @@",
        *[f"+{ln}" for ln in lines],
    ]


def makefile_head_hunk(add_lines: list[str], anchor: list[str]) -> list[str]:
    """在 Makefile 头部 SPDX 注释块之后插入 add_lines。

    anchor 是 Makefile 开头的 N 行（不加 + 前缀），作为上下文。
    生成 @@ -1,N +1,N+len(add) @@，把 add 放在 anchor 最前面
    （即插到文件最顶部，锚点整体后移）—— 这是 0002 成功用过的稳妥做法。
    """
    n = len(anchor)
    return [
        "diff --git a/drivers/misc/Makefile b/drivers/misc/Makefile",
        "--- a/drivers/misc/Makefile",
        "+++ b/drivers/misc/Makefile",
        f"@@ -1,{n} +1,{n + len(add_lines)} @@",
        *[f"+{ln}" for ln in add_lines],
        *[f" {ln}" for ln in anchor],
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-root", default=None,
                    help="解包好的内核源码树，生成后对其做 patch --dry-run")
    args = ap.parse_args()

    patch: list[str] = []

    # 1) 两个新驱动源文件
    for name in DRIVERS:
        src = os.path.join(REPO, "kernel-modules", name, name + ".c")
        if not os.path.exists(src):
            sys.exit(f"找不到 {src}")
        with open(src, encoding="utf-8") as f:
            code = f.read()
        patch += new_file_hunk(f"drivers/misc/{name}.c", code)

    # 2) Makefile：头部插入两条 obj-m，锚点用文件头 SPDX 注释块
    anchor = [
        "# SPDX-License-Identifier: GPL-2.0",
        "#",
        "# Makefile for misc devices that really don't fit anywhere else.",
        "#",
    ]
    add = [
        "",
        "# rk3399-mid: 板级驱动（module 形式）",
        "obj-m\t\t\t\t+= es7243.o",
        "obj-m\t\t\t\t+= hr8833.o",
    ]
    patch += makefile_head_hunk(add, anchor)

    out = os.path.join(PATCH_DIR, OUT_NAME)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(patch) + "\n")
    print(f"written {out}  ({len(patch)} 行)")

    # 3) dry-run 验证
    if args.verify_root:
        root = args.verify_root
        # 确认锚点真的匹配目标树
        mf = os.path.join(root, "drivers/misc/Makefile")
        with open(mf, encoding="utf-8") as f:
            head = f.read().splitlines()[:4]
        if head != anchor:
            print("WARN: 目标树 Makefile 头部与锚点不一致：", head)
        r = subprocess.run(
            ["patch", "--dry-run", "-p1", "-d", root, "-i", os.path.abspath(out)],
            capture_output=True, text=True)
        print("patch --dry-run:", "OK" if r.returncode == 0 else f"FAIL(rc={r.returncode})\n{r.stdout}\n{r.stderr}")
        if r.returncode != 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
