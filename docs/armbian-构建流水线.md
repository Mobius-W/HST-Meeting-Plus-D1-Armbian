# RK3399-MID Armbian 构建流水线（云端）

> 目标：用官方 `armbian/build` 源码，在 GitHub Actions 上直接编出可用的
> `armbian .img` + `uboot.img` + `trust.bin` + `rk3399-mid.dtb`。
> **不 fork armbian/build**，全部通过本仓库的 `armbian/userpatches/` 注入。
> 最后更新：2026-11-11

---

## 一、免 fork 注入的全部文件

| 文件 | 作用 | 被谁读 |
|---|---|---|
| `armbian/userpatches/config/boards/rk3399-mid.csc` | 板级配置 + 4 个 hook | `config_source_board_file()`（`config-prepare.sh:95`），按 `conf → wip → csc → eos → tvb` 顺序在 `${SRC}/config/boards` 与 `${USERPATCHES_PATH}/config/boards` 两处找 |
| `armbian/userpatches/kernel/archive/rockchip64-6.18/dt/rk3399-mid.dts` | 内核设备树（裸 DTS，不用写 patch） | 内核 patch 目录的 `0000.patching_config.yaml` 声明 `dts-directories: dt → arch/arm64/boot/dts/rockchip`，并由 `dt_makefile_patcher.copy_bare_files()` + `auto-patch-dt-makefile` 自动改写 Makefile |
| `armbian/userpatches/u-boot/v2026.10/add-trust-ini.patch` | 补 `trust.ini`（见 §3.2） | `PATCH_DIRS_TO_APPLY=${BOOTPATCHDIR}` → `lib/tools/patching.py` |
| `armbian/blobs/stock-parm.bin` | 原厂 parameter 原始 898 B | `tools/mk-parm-variant.py` |
| `tools/mk-parm-variant.py` | GPT 镜像 → 「PARM + MBR」变体 | CI 第 6 步 |

**目录优先级**：`CONST_PATCH_ROOT_DIRS` 同时收 `${USERPATCHES_PATH}/<type>/<dir>` 与 `${SRC}/patch/<type>/<dir>`；
`copy_bare_files()` 按 `['core','user']` 顺序遍历，**user 最后 → 同名文件以 userpatches 为准**。

`USERPATCHES_PATH` 默认 `${SRC}/userpatches`，CI 里由 `rsync custom/armbian/userpatches/ build/userpatches/` 铺好。

---

## 二、U-Boot 选型与产物

```bash
BOOTCONFIG="evb-rk3399_defconfig"   # 上游 mainline 自带，v2022.04~v2026.10 全存在
BOOTBRANCH_BOARD="tag:v2026.10"
BOOTPATCHDIR="v2026.10"
BOOT_SOC="rk3399"                   # 必须显式，见 §3.1
BOOT_SCENARIO="only-blobs"
```

`only-blobs` 产物链（`rockchip64_common.inc` 的 `uboot_custom_postprocess()`）：

```
u-boot-dtb.bin --loaderimage --pack --uboot ... uboot.img 0x200000   → LOADER 容器
trust_merger --replace bl31.elf <rkbin>/BL31_BLOB trust.ini          → trust.bin (BL3X)
mkimage -T rksd ... + miniloader blob                                → idbloader.bin（本板不落盘）
```

本板实测产出：`u-boot-dtb.bin` 956096 B，`uboot.img` load addr 0x200000，编译耗时 37 s。

---

## 三、四个踩过的坑（都是构建期硬失败，不是运行期）

### 3.1 `BOOT_SOC` 推不出来

`rockchip64_common.inc:75` 的推导是

```bash
expr "${BOOTCONFIG}" : '.*\(rk[[:digit:]]\+.*\)_.*'
```

对 `evb-rk3399_defconfig` 推出的是 `rk3399` 之外的东西（带后缀），`case "$BOOT_SOC" in rk3399)`
分支不命中 ⇒ `BOOT_SCENARIO` / `DDR_BLOB` / `MINILOADER_BLOB` / `BL31_BLOB` 全空。
**必须在板级显式 `BOOT_SOC="rk3399"`**，并在 `post_family_config` 里断言三个 blob 非空。

### 3.2 `trust.ini` —— 覆写 `BOOTPATCHDIR` 会丢补丁（CI #43005314503 的失败原因）

```
rockchip64_common.inc:22   BOOTPATCHDIR="${BOOTPATCHDIR:-"u-boot-rockchip64"}"
common.conf:189            BOOTBRANCH="${BOOTBRANCH_BOARD:-"tag:v2022.07"}"
```

即：**家族默认是「v2022.07 + u-boot-rockchip64 补丁目录」**。`add-trust-ini.patch`（298 B，只新增一个 15 行
`trust.ini`）就在 `patch/u-boot/u-boot-rockchip64/` 里。一旦把 `BOOTPATCHDIR` 覆写成 `v2026.10`，
补丁列表变成 11 个（日志 `11 total patches; 11 applied`），`trust.ini` 消失，于是：

```
[u-boot:1} Postprocessing u-boot
[rk3399-mid] boots with only-blobs scenario
[...] pack uboot.img success!
[...] config(trust.ini) not found!
[...] merge failed!            → Error 255, uboot_custom_postprocess() @ rockchip64_common.inc:325
```

**修法**：`u-boot-rockchip64/` 里另外 47 个补丁是给 v2022.07 的，不能整体带进来；只在
`userpatches/u-boot/v2026.10/` 放一份与官方逐字节相同的 `add-trust-ini.patch` 即可。

### 3.3 `DEFAULT_FDT_FILE` 不能指向本板 DTB

`evb-rk3399_defconfig` 自带 `CONFIG_DEFAULT_FDT_FILE="rockchip/rk3399-evb.dtb"`，而这个 DTB 是
**U-Boot 自己**用的（`u-boot-dtb.bin` 由 `CAT u-boot-nodtb.bin dt.dtb` 拼成）。把它改成
`rockchip/rk3399-mid.dtb` 会让 U-Boot 自身 FDT 加载失败。
内核用的 DTB 走另一条完全独立的链路：`armbianEnv.txt` 的 `fdtfile=`。

### 3.4 ARM64 上 `CMD_BOOTI` 默认是关的

U-Boot v2026.10：

```
CONFIG_ROCKCHIP_RK3399=y
  → imply BOOTSTD_FULL            (arch/arm/mach-rockchip/Kconfig:280)
  → imply BOOTSTD_DEFAULTS → select BOOT_DEFAULTS
  → select BOOT_DEFAULTS_CMDS if CMDLINE
  → select CMD_EXT2/EXT4/FAT/FS_GENERIC/PART      ← 文件系统命令是自动带出的
```

**唯一真缺口**：`config CMD_BOOTI` 有 `depends on LMB`，而 `lib/Kconfig` 里 `config LMB` 的
`default y if ...` 列表**不含 ARM64**（全树只有 `EFI_LOADER` select 它）⇒ `CMD_BOOTI` 不被带出，
而 `boot-rockchip64.cmd` 结尾就是 `booti`。

⇒ 用 `post_config_uboot_target`（在 `make ${BOOTCONFIG}` 之后、`make olddefconfig` 之前，此时 `.config`
已存在）显式 `--enable CONFIG_LMB` + `CONFIG_CMD_BOOTI`，并防御性补齐 FS/PART/MMC/GPT。
**不能用 `pre_config_uboot_target`** —— 它在 `make defconfig` 之前，`.config` 还不存在。

---

## 四、引导路径（v2026.10 走 BOOTSTD，不走 distro_bootcmd）

- `BOOTSTD_BOOTCOMMAND default y if !DISTRO_DEFAULTS` ⇒ `bootcmd = bootflow scan`
- `BOOTMETH_SCRIPT`（`default y if BOOTSTD_FULL`）在 `boot/Kconfig` 的 help 里明写找 `boot/boot.scr`
- `boot/bootmeth_script.c` 会 `env_set` 出 `devtype` / `devnum` / `distro_bootpart` / `prefix`
  ⇒ `boot-rockchip64.cmd` 里的 `${devtype} ${devnum}:${distro_bootpart} ${prefix}armbianEnv.txt`
  全部有值，**不需要 distro_bootcmd**（`include/config_distro_bootcmd.h` 在 rockchip 板上根本没被 include）

rockchip64 家族不设 `BOOTFS_TYPE` ⇒ 只有一个 rootfs 分区、`/boot` 在分区内部：

```
p1:/boot/boot.scr              ← mkimage -T script
p1:/boot/armbianEnv.txt        ← 追加 fdtfile=rockchip/rk3399-mid.dtb
p1:/boot/dtb -> dtb-6.18.x     ← kernel-debs.sh 建符号链接
p1:/boot/dtb/rockchip/rk3399-mid.dtb
```

本板因此**不设 `SRC_EXTLINUX`**（官方 `fine3399.csc` 设了，但我们会自写 MBR，extlinux 用不上）。

---

## 五、写盘坐标（本板 boot0 miniloader 决定）

原厂 `PARM` 的 mtdparts 写死了 `uboot@0x2000`(=LBA8192) 与 `trust@0x4000`(=LBA16384)，
官方 only-blobs 默认是 64 / 16384 / 24576，必须覆盖。

**关键机制**：`uboot.sh:558` 生成 deb 里的 `platform_install.sh` 时用的是
`$(declare -f write_uboot_platform || true)` —— 抓的是**当时**的定义。所以只要在
`post_family_config` 里先 `unset` 再重定义，覆盖就会同时进入

- 镜像组装：`lib/functions/image/loop.sh:91` `write_uboot_platform "${TEMP_DIR}${DIR}" "$loop"`
- 板端 `armbian-install`

```bash
function write_uboot_platform() {
    dd if=$1/uboot.img of=$2 bs=512 seek=8192  conv=notrunc status=none
    dd if=$1/trust.bin of=$2 bs=512 seek=16384 conv=notrunc status=none
}
```

`idbloader.bin` **不写**：本板 boot0 里已有原厂 miniloader，user 区 LBA64 不被任何东西读。

---

## 六、PARM 与 GPT 的冲突（方案 C）

| 事实 | 数值 |
|---|---|
| user 区 LBA0 = `PARM` + u32 长度 0x382(898) + CRLF 文本 | 文本跨 LBA0 + LBA1 前 386 B |
| 文本里 mtdparts 的 `uboot@0x2000` / `trust@0x4000` 两段 | 落在 **LBA0 的 435..510 字节** |
| MBR 分区表区 | LBA0 的 **446..509** |
| GPT 头 / entry array | LBA1 / LBA2..34 |

⇒ 不能既放完整 898 B PARM 又放 MBR；GPT 还会把 LBA1 写掉。

**方案 C（已实现并单测）**：`tools/mk-parm-variant.py`

```
LBA0[0 : 446]    = 压缩版 parameter（丢弃最长的 '#' 注释行直到 <=446，mtdparts 只留 uboot/trust/misc/resource）
LBA0[446 : 512]  = MBR 分区项（type 0x83，CHS 用 0xFE/0xFF/0xFF）+ 0x55AA
LBA1 .. LBA34    = 清零（抹 GPT 头与 entry array）
末尾 33 个 LBA   = 清零（抹 secondary GPT）
```

压缩后 parameter **正好 446 B**，最后一行是：

```
CMDLINE: androidboot.hardware=rk30board init=/init mtdparts=rk29xxnand:0x00002000@0x00002000(uboot),0x00002000@0x00004000(trust),0x00002000@0x00006000(misc),0x00008000@0x00008000(resource)
```

用法：`python3 tools/mk-parm-variant.py <in.img> <out.img> [--parm armbian/blobs/stock-parm.bin] [--report]`

CI 第 6 步会自动产出 `*-parm.img` 并回读校验（PARM 长度、MBR slot、0x55AA、LBA1 已清零）。

---

## 七、CI 结构（`.github/workflows/build-armbian.yml`）

| # | 步骤 | 说明 |
|---|---|---|
| 1-3 | checkout | 本仓库 → `custom/`；`armbian/build@main` → `build/`；`armbian/os` → `os/` |
| 4 | Prepare userpatches | `rsync os/userpatches` + `rsync custom/armbian/userpatches` |
| 5 | Install build requirements | `sudo ./compile.sh requirements` + `chown`（**build 本身不能用 root 跑**，`compile.sh` 会自动 relaunch 进 `ghcr.io/armbian/docker-armbian-build:armbian-ubuntu-noble-latest`） |
| 6 | Build | `./compile.sh build BOARD=rk3399-mid BRANCH=current RELEASE=noble BUILD_MINIMAL=yes KERNEL_CONFIGURE=no COMPRESS_OUTPUTIMAGE=img` |
| 7 | Verify | 解 `linux-u-boot-rk3399-mid-*.deb` 看 `uboot.img`/`trust.bin` 魔数；回读镜像 LBA0/1/64/8192/16384/24576/32768 |
| 8 | PARM variant | 生成并校验 `-parm.img`（失败不阻断主产物） |
| 9 | Collect + upload | 镜像、deb、`boot-uboot.img`/`boot-trust.bin`、`rk3399-mid.dtb` |

---

## 八、构建史

| run | sha | 结果 | 说明 |
|---|---|---|---|
| #43005314503 | 1c8949c | ❌ | `trust.ini` 缺失（§3.2）——U-Boot 本体 37 s 成功，仅 `trust_merger` 失败 |
| #43009803786 | 48ca8ec | ✅ **成功** | 补 `add-trust-ini.patch` + 去掉 `DEFAULT_FDT_FILE` 覆写；11:11→13:04，约 113 min |

## 八之二、成功构建的产物实证（run #43009803786）

时间线：`11:11:00` 起 → `11:14` U-Boot deb 完成（含 `uboot.img`/`trust.bin`/`idbloader.bin`）→ `12:57` 内核 + dtb deb → `12:58` bsp-cli → `13:03` 镜像落盘（1824 MiB）→ `13:04` 上传 artifact 1421005134 B。

**引导件魔数（从 `linux-u-boot-rk3399-mid-current_*.deb` 解出）**

| 文件 | 大小 | 头 32 B | 判定 |
|---|---|---|---|
| `uboot.img` | 4194304 | `4c4f414445522020 000000000000 00002000 c0960e00 …` | `LOADER  `，load addr **0x00200000**，payload 0x000ec096（967,894 B） |
| `trust.bin` | 4194304 | `424c3358 00010000 23000000 ec000300` | `BL3X`，与 11-10 实测可跑的 `ec 00 03 00` **逐字节同款** |
| `idbloader.bin` | 217372 | — | 仅打包不落盘（boot0 已有原厂 miniloader） |

**标准镜像扇区布局（GPT 方案）**

```
LBA      0  PARM/MBR 区    00 00 00 00 00 00 00 00   全零（GPT 保护 MBR 未写，因 LBA0 留给 PARM）
LBA      1  GPT 头         45 46 49 20 50 41 52 54   "EFI PART"
LBA     64  idbloader 区   00 ...                     本板不写 ✓
LBA   8192  LOADER         4c 4f 41 44 45 52 20 20   "LOADER  " ✓
LBA  16384  BL3X           42 4c 33 58 00 01 00 00   "BL3X" ✓
LBA  24576  trust 备用区   00 ...                     空 ✓
LBA  32768  p1 起点        00 ...  (p1 = 32768..3733503, rootfs)
image size = 1824.0 MiB
```

> ⚠ 标准镜像的 LBA0 是**全零**，即**没有 PARM**。要恢复原厂 PARM 必须用 `-parm.img` 变体。

**PARM 变体校验（同一 run 第 9 步）**

```
LBA0 magic     : b'PARM'
PARM 长度      : 446 字节（<= 446 ✓）
MBR slot1      : type=0x83 first=32768 count=3700736 last=3733503
MBR 签名       : 55aa
LBA1 (GPT 头)  : 全零 ✓
镜像大小       : 1824.0 MiB
压缩 mtdparts  : rk29xxnand:0x00002000@0x00002000(uboot),0x00002000@0x00004000(trust),
                 0x00002000@0x00006000(misc),0x00008000@0x00008000(resource)
```

**链条各环节日志证据**

| 环节 | 日志行 | 内容 |
|---|---|---|
| board 配置加载 | 466 | `Sourcing board configuration [ …/rk3399-mid.csc ]` |
| BOOT_SOC 推导 | 500 | `[ BOOT_SOC=rk3399 BOOT_SCENARIO=only-blobs BOOTCONFIG=evb-rk3399_defconfig ]` |
| 写盘覆盖 | 502-503 | `Overriding write_uboot_platform()` / `uboot.img -> LBA8192, trust.bin -> LBA16384, idbloader.bin NOT written` |
| u-boot 配置补丁 | 761 | `Enabling partition/ext4/booti support in U-Boot for boot.scr loading` |
| u-boot 打补丁 | 651 | `12 total patches; 12 applied`（含 `add-trust-ini`，此前只有 11） |
| trust 合并 | 1528 | `merge success(trust.bin)` |
| 内核打补丁 | 2083 | `267 total patches; 267 applied` |
| DTS 编译 | 3858 | `DTC arch/arm64/boot/dts/rockchip/rk3399-mid.dtb`（85,273 B） |
| DTB 安装 | 36095 | `INSTALL …/dtbs/rockchip/rk3399-mid.dtb` |
| boot 脚本部署 | 37048-37170 | `boot-rockchip64.cmd -> /boot/boot.cmd`（`boot.scr` 由 bsp-cli postinst 的 `mkimage` 生成，`armbian-bsp-cli-deb.sh:394`） |
| armbianEnv | 37171 | `config/bootenv/rockchip64.txt -> /boot/armbianEnv.txt` |

## 九、待办

1. 拿到 `.img` 后在真机按 LBA 分件验证（先读回、再写），**绝不整盘覆盖 LBA0**。
2. eDP 面板 / GT9xx / ES8316 / CW2015 的实测校准（DTS 文件头列了 3 项待校准）。
3. `linux/rk3399-mid.dts` 与 `armbian/userpatches/.../dt/rk3399-mid.dts` 目前是两份副本，后续合并为一处。
4. 确认镜像内 `/boot/boot.scr` 确实存在（BOOTSTD 的 `BOOTMETH_SCRIPT` 只认 `boot/boot.scr`，`boot.cmd` 不算）。
