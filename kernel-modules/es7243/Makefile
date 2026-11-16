# SPDX-License-Identifier: GPL-2.0-only
#
# rk3399-mid 音频复合 codec（ES7148 播放 + 2x ES7243 麦阵采集）
#
# 树外模块：对着设备上正在跑的 6.18.63-current-rockchip64 的 linux-headers
# 编译，vermagic 天然一致，scp 上去 insmod 即可，不用重刷内核。
#
# 手工编译：
#   make -C <linux-headers-6.18.63-current-rockchip64> M=$PWD \
#        ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-gcc-14 modules

obj-m := es7243.o
