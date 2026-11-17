#!/usr/bin/env bash
# 编译前本地确认：在推 CI 之前，用与构建完全相同的内核版本做 patch 预检。
#
# 背景（2026-11-17 反复失败的教训）：
#   1. 0001/0003 两个驱动 patch 都改 drivers/misc/Makefile 尾部 @@-75，
#      单独 git apply --check 都 OK，但顺序 apply 时第二个失配 → CI 第 8 分钟才暴露。
#   2. workflow 用 KERNELBRANCH=branch:linux-6.18.y 滚动，6.18.63→6.18.64
#      主线吸收了 armian 官方 general-can patch，导致 reversed 失败。
#
# 本脚本做三件事：
#   A. 确认 workflow 里 KERNELBRANCH 已 pin（防止又滚到新版本）
#   B. 拉 pin 版本内核的 patch 目标文件，按顺序 git apply 所有 userpatches
#   C. （可选）检查 armian 官方 patch 在 pin 版本是否 reversed
#
# 用法：
#   tools/preflight-build.sh
#   tools/preflight-build.sh --kver 6.18.63
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PDIR="$REPO/armbian/userpatches/kernel/archive/rockchip64-6.18"

# --- A. 确认内核版本已 pin ---
PIN=$(grep -oE 'KERNELBRANCH=[^ ]+' "$REPO/.github/workflows/build-armbian.yml" | head -1 || true)
if [[ -z "$PIN" || "$PIN" == "KERNELBRANCH=branch:"* ]]; then
  echo "FAIL: workflow 未 pin 内核版本（当前: ${PIN:-无}）；滚动分支会导致官方 patch reversed。"
  echo "      请把 KERNELBRANCH 设为 tag:<ver> 或 commit:<sha>。"
  exit 1
fi
KVER_FROM_PIN="${PIN#KERNELBRANCH=tag:}"
KVER="${KVER_FROM_PIN#KERNELBRANCH=commit:}"
KVER="${1:-}"
if [[ -z "${KVER:-}" ]]; then
  # 从 pin 里提取版本数字
  KVER=$(grep -oE 'KERNELBRANCH=tag:v?[0-9]+\.[0-9]+\.[0-9]+' "$REPO/.github/workflows/build-armbian.yml" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
fi
[[ -z "$KVER" ]] && { echo "FAIL: 无法从 workflow 推断内核版本，请用 --kver 指定"; exit 1; }
echo "[preflight] pinned kernel = $KVER  ($PIN)"

# --- B. 拉内核目标文件、顺序 apply 所有 userpatches ---
TREE="${TMPDIR:-/tmp}/rk3399-preflight-$$"
trap 'rm -rf "$TREE"' EXIT
mkdir -p "$TREE/drivers/misc" "$TREE/drivers/media/i2c"
BASE="https://raw.githubusercontent.com/gregkh/linux/v${KVER}"
echo "[preflight] fetching kernel v${KVER} patch targets from $BASE ..."
for f in drivers/misc/Makefile drivers/misc/Kconfig drivers/media/i2c/Makefile drivers/media/i2c/Kconfig; do
  curl -fsSL "$BASE/$f" -o "$TREE/$f"
done

git -C "$TREE" init -q
git -C "$TREE" add -A
git -C "$TREE" -c user.email=a@b -c user.name=preflight commit -qm base

echo "[preflight] applying userpatches SEQUENTIALLY (this catches the @-75 collision):"
shopt -s nullglob
patches=("$PDIR"/*.patch)
[[ ${#patches[@]} -eq 0 ]] && { echo "FAIL: 没有找到 userpatches"; exit 1; }
for p in "${patches[@]}"; do
  printf '  %-48s ' "$(basename "$p")"
  if git -C "$TREE" apply "$p" 2>"$TREE/.err"; then
    echo OK
  else
    echo FAIL
    sed 's/^/      /' "$TREE/.err"
    echo "[preflight] ABORT — patch 顺序应用失败，不要 push。"
    exit 1
  fi
done
echo "[preflight] PASS — 所有 kernel userpatches 顺序应用干净。"
