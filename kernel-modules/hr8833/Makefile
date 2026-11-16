# SPDX-License-Identifier: GPL-2.0-only
#
# hr8833 云台电机驱动 —— 树外（out-of-tree）构建入口
#
# 为什么走树外：
#   设备上跑的 6.18.63-current-rockchip64 是已经编好并正在运行的内核。
#   如果把驱动塞进内核重新编译，Armbian 的版本串/配置一变，vermagic 就对不上，
#   insmod 会被拒（"version magic ... should be ..."），只能整机重刷。
#   而树外模块直接对着一模一样的 linux-headers 编译，vermagic 天然一致，
#   编出来就能 scp 上去 insmod，迭代以分钟计。
#
# 手工用法（在 Linux 上，或用 CI）：
#   make -C <linux-headers-6.18.63-current-rockchip64> M=$PWD \
#        ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- modules
#
# 装机（设备上）：
#   mkdir -p /lib/modules/$(uname -r)/extra && cp hr8833.ko $_
#   depmod -a && modprobe hr8833

obj-m := hr8833.o
#
# 注意：内核 6.18 的 Makefile 无条件加 -fmin-function-alignment=8（GCC 14+），
#      交叉编译必须用 gcc-14-aarch64-linux-gnu，gcc-13 会报
#      "unrecognized command-line option"。
