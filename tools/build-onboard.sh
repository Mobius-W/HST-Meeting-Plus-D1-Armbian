#!/bin/sh
#
# 在 RK3399-MID 板上原生编译树外内核模块。
#
# 为什么不用交叉编译：板上内核是 gcc 14.2 编的，板上原生用 gcc-14 编出的
# vermagic 天然一致（6.18.63-current-rockchip64 SMP preempt mod_unload aarch64），
# 不依赖 GitHub Actions，也不需要 --force-vermagic。
#
# 前置（一次性）：
#   apt-get install -y --no-install-recommends gcc-14 make bison flex \
#       libssl-dev libelf-dev m4
#   dpkg -i prebuilt/linux-headers-current-rockchip64_*_6.18.63_*.deb
#
#   ★ 该 headers deb 由 armbian 打包时裁掉了 scripts/basic/fixdep 与
#     scripts/mod/modpost（它们是「宿主程序」，交叉编译时需要外借）。
#     板上原生编译时宿主 == 目标，直接自己编即可 —— 本脚本自动补。
#
# 用法：./build-onboard.sh [模块目录]     （默认 /root/hr8833）
#
set -eu

KDIR=$(uname -r)
HDR=$(readlink -f "/lib/modules/$KDIR/build")
MOD=${1:-/root/hr8833}
CC=${CC:-gcc-14}

echo "==> kernel : $KDIR"
echo "==> headers: $HDR"
echo "==> module : $MOD"

[ -d "$HDR" ] || { echo "缺少 $HDR：先装 linux-headers deb" >&2; exit 1; }
[ -f "$MOD/Makefile" ] || { echo "$MOD 里没有 Makefile" >&2; exit 1; }

# ---- 补 scripts/basic/fixdep ----
if [ ! -x "$HDR/scripts/basic/fixdep" ]; then
	echo "==> 编译 fixdep（headers 里被裁掉）"
	"$CC" -O2 -I"$HDR/scripts/include" \
		-o "$HDR/scripts/basic/fixdep" "$HDR/scripts/basic/fixdep.c"
fi

# ---- 补 scripts/mod/modpost ----
# modpost 依赖 devicetable-offsets.h（同样是生成头，headers 里没有），
# 自己重建很脆，所以默认从发行版 headers 借同架构二进制。
if [ ! -x "$HDR/scripts/mod/modpost" ]; then
	echo "==> 缺少 modpost，尝试从发行版 headers 借（arm64 原生）"
	BORROWED=$(ls /usr/src/linux-headers-*/scripts/mod/modpost 2>/dev/null | head -1 || true)
	if [ -n "$BORROWED" ]; then
		cp "$BORROWED" "$HDR/scripts/mod/modpost"
		chmod +x "$HDR/scripts/mod/modpost"
		echo "    borrowed <- $BORROWED"
	else
		cat >&2 <<-EOF
		没有可借的 modpost。二选一：
		  a) apt-get download linux-headers-\$(uname -r | sed 's/-.*//')-generic
		     dpkg-deb -x <deb> /tmp/h && cp /tmp/h/usr/src/linux-headers-*/scripts/mod/modpost $HDR/scripts/mod/
		  b) 用 GitHub Actions 的 .github/workflows/build-modules.yml（需能 push）
		EOF
		exit 1
	fi
fi

# ---- 编译 ----
# 注意：绝对不要跑 `make scripts` / `make prepare`，
#       那会重生成 include/generated/autoconf.h 并在失败时把它删掉。
make -C "$HDR" M="$MOD" CC="$CC" modules

echo
echo "==> 产物"
ls -l "$MOD"/*.ko
for ko in "$MOD"/*.ko; do
	modinfo "$ko" | grep -E '^(vermagic|description):' || true
done

cat <<-EOF

装载：
  rmmod hr8833 2>/dev/null || true
  insmod $MOD/hr8833.ko

持久化：
  cp $MOD/hr8833.ko /lib/modules/$KDIR/extra/ && depmod -a

调试参数：
  echo Y > /sys/module/hr8833/parameters/auto_reset   # 打开启动前 nSLEEP 自愈
EOF
