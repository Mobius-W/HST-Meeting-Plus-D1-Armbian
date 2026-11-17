# RK3399-MID (视频会议一体机 / 圆板)
#
# ★ 2026-11-15 22:xx 方向切换（用户拍板）：完全对齐 armbian 官方 mainline 引导链。
#   基线 = armbian/build 官方 config/boards/rockpi-4b.csc
#         + config/sources/vendors/radxa/rk3399-uboot.conf.sh
#   证据 = docs/引导机制判定-20261115.md（字节级）
#
#   1. WF7000A 实盘 Armbian 与 rockpi4b 官方镜像前 16 MiB 逐字节零差异；
#      原厂 Android 的 PARM / LOADER@8192 / BL3X@16384 / RSCE@32768 全部消失。
#      ⇒ Armbian 引导与 Android 引导机制无关，唯一交集是 BootROM 读 eMMC user LBA64。
#   2. 官方链：BOOT_SCENARIO=binman-atf-mainline，产物是**单个 u-boot-rockchip.bin**，
#      由 family 官方 write_uboot_platform() 一次写 dd bs=32k seek=1（= LBA64）。
#      文件内布局（实测 dist/u-boot-rockchip.bin 与 WF7000A 实盘一致）：
#          IDB (DDR blob TPL + SPL)           @ 0x000000  -> 落盘 LBA64
#          FIT + external data (TF-A/U-Boot) @ 0x7F8000  -> 落盘 LBA16384
#      FIT 内含 mainline TF-A bl31 + U-Boot proper + fdt，
#      **不需要** vendor trust / bl30 / bl32，也不读 PARM / mtdparts。
#   3. 本板 DRAM = 4 GB LPDDR4（丝印 + TTL 训练日志双证，416→856 MHz）；
#      radxa 默认 DDR_BLOB = rk33/rk3399_ddr_933MHz_v1.30.bin（2023-04-17，与 TTL 同版），
#      WF7000A 实盘引导区实证含 lpddr4_set_ctl / lpddr4_set_rate。
#   4. 板级差异只换内核 DTB（BOOT_FDT_FILE），U-Boot 沿用官方 rock-pi-4 defconfig，
#      与 WF7000A 首次成功刷入 Armbian 的路径完全一致。
#   5. 已作废（vendor only-blobs 路线）：PARM@LBA0、LOADER@8192、BL3X@16384、
#      trust.ini 补丁依赖、自建 MBR hook、-parm/-dualparm 变体、BOOT_SOC 显式指定、
#      自定义 write_uboot_platform() 覆盖。旧版留档
#      docs/_废弃-vendor-only-blobs-csc-20261115.bak
#
# 本文件刻意保持极简：不覆盖 write_uboot_platform()、不设 IMAGE_PARTITION_TABLE、
# 不设 BOOT_SOC / BOOT_SCENARIO / BOOTBRANCH_BOARD / BOOTPATCHDIR / SERIALCON
#（全部交给官方 radxa conf 与 rockchip64 family 的 late hook）。

BOARD_NAME="RK3399-MID"
BOARD_VENDOR="rk3399-mid"
BOARDFAMILY="rockchip64"
BOARD_MAINTAINER="Mobius-W"
INTRODUCED="2026"

# ---- 内核 ---------------------------------------------------------------
KERNEL_TARGET="current"
KERNEL_TEST_TARGET="current"

# ---- U-Boot：官方 rockpi-4b.csc 原样 ------------------------------------
BOOTCONFIG="rock-pi-4-rk3399_defconfig"

# 官方靠 family 的 expr 从 defconfig 名推导 BOOT_SOC；本机 BSD expr 对 "\+" 实测返回空，
# GNU expr（CI runner）则能推出 rk3399。显式写死消除实现差异，避免
# ATF_TARGET_MAP 里 PLAT= 为空。board 先于 family 加载，radxa 设的
# DDR_BLOB=v1.30 不会被 family 的 ${DDR_BLOB:-v1.25} 覆盖。
BOOT_SOC="rk3399"

# ---- 内核设备树：本板专用，替换官方 rock-pi-4b --------------------------
# 源码 userpatches/kernel/archive/rockchip64-6.18/dt/rk3399-mid.dts
# radxa conf 的 post_config_uboot_target hook 会把它同时写进 U-Boot 的
# CONFIG_DEFAULT_FDT_FILE（与官方 rockpi-4b 行为一致）；内核 DTB 由
# armbianEnv.txt / boot.scr 从 /boot/dtb/ 加载。
BOOT_FDT_FILE="rockchip/rk3399-mid.dtb"

# ---- 唯一的引导链定义：armbian 官方 radxa RK3399 共用配置 ----------------
#   BOOTBRANCH_BOARD = tag:v2026.10     BOOTPATCHDIR = v2026.10
#   BOOT_SCENARIO    = binman-atf-mainline
#   DDR_BLOB         = rk33/rk3399_ddr_933MHz_v1.30.bin (LPDDR4)
#   ATF              = TF-A lts-v2.14.11, PLAT=rk3399 -> bl31.elf 编进 FIT
#   UBOOT_TARGET_MAP = "BL31=bl31.elf ROCKCHIP_TPL=...;;u-boot-rockchip.bin"
#   write_uboot_platform()（family 官方实现）:
#       dd if=u-boot-rockchip.bin of=$IMG bs=32k seek=1 conv=notrunc
source "${SRC}/config/sources/vendors/radxa/rk3399-uboot.conf.sh"

# ---- 摄像头：rkisp1 + Sony IMX307（2026-11-16）---------------------------
# Armbian 官方 rockchip64 defconfig 默认不开 rkisp1，也不含本板移植的
# imx307 驱动。用 custom_kernel_config hook 增量打开，避免整份 .config
# 覆盖（那会让后续内核升级失去官方默认值）。
# 依赖链：ISP1 在 6.18 的 Kconfig 是
#   config VIDEO_ROCKCHIP_ISP1  tristate
#       depends on V4L_PLATFORM_DRIVERS
#       depends on VIDEO_DEV && OF
#       depends on ARCH_ROCKCHIP || ARCH_MXC || COMPILE_TEST
# ★ 2026-11-17 事故修正（核查 run 43993856054 产物的 .config 发现）：
#   第一版只写了 CONFIG_VIDEO_ROCKCHIP_ISP1=y，结果 .config 里**根本没有这个符号**
#   （既没有 =y，也没有 "# ... is not set"）。根因是
#   `# CONFIG_V4L_PLATFORM_DRIVERS is not set` —— 依赖不满足时 Kconfig 让符号不可见，
#   scripts/config 写进去的 =y 被随后的 olddefconfig 直接抹掉，连痕迹都不留。
#   同时 VIDEO_DEV=m，ISP1 若要 =y 还得把 VIDEO_DEV 一并提到 y，污染面更大。
#   ⇒ 正确做法：V4L_PLATFORM_DRIVERS 与 ISP1 都放 opts_m，走模块 rockchip-isp1.ko。
#   （名字用 armbian 的扩展命名法 hook__扩展名，框架会自动合成 custom_kernel_config 包装器。）
function custom_kernel_config__rk3399_mid_camera() {
	opts_m+=(
		# ISP1 的前置：缺了它 ISP1 连符号都不会出现在 .config 里
		CONFIG_V4L_PLATFORM_DRIVERS
		CONFIG_VIDEO_ROCKCHIP_ISP1
		# sensor
		CONFIG_VIDEO_IMX307
		CONFIG_VIDEO_V4L2_I2C
		CONFIG_V4L2_ASYNC
		CONFIG_V4L2_CCI_I2C
		CONFIG_REGMAP_I2C
		# MIPI CSI-2 PHY
		CONFIG_PHY_ROCKCHIP_INNO_CSIDPHY
		CONFIG_PHY_ROCKCHIP_DPHY_RX0
	)
	kernel_config_modifying_hashes+=("rk3399_mid_camera=$(declare -f custom_kernel_config__rk3399_mid_camera | sha256sum | cut -d ' ' -f1)")
}
