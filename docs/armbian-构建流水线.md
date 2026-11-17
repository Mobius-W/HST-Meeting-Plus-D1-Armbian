# RK3399-MID Armbian 构建流水线（云端）

> 目标：用官方 `armbian/build` 源码，在 GitHub Actions 上直接编出可用的
> `armbian .img` + `uboot.img` + `trust.bin` + `rk3399-mid.dtb`。
> **不 fork armbian/build**，全部通过本仓库的 `armbian/userpatches/` 注入。
> 最后更新：2026-11-17（新增 §十 构建耗时与增量路径）
>
> ⚠ **§二 / §五 / §六 / §八 属 only-blobs 时代（≤2026-11-14）的记录，已作废**：
> 11-15 起引导链切到 mainline `binman-atf-mainline`，引导件只剩单一 `u-boot-rockchip.bin`
> （IDB@LBA64 + FIT@LBA16384 + MBR p1@32768），`trust.ini` / PARM 变体均不再使用。
> 现状以 `.github/workflows/build-armbian.yml` 头部注释与 `docs/引导机制判定-20261115.md` 为准。

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

### 3.5 内核 userpatch 顺序应用冲突 + 内核版本滚动（2026-11-17 run #44079575914 失败根因）

**现象**：`Failed to apply 3 patches`（compile.sh 的 kernel patching 阶段，第 8 分钟才暴露）：
`0001-misc-add-es7243`、`0003-misc-add-hr8833`（我们的）+ `general-can-3-dev-can_put_echo_skb`（armian 官方）。

**两个独立根因**：

1. **我们的 patch 顺序冲突（主因，可完全本地复现）**：
   0001 和 0003 各自把一条 `obj-m += …` 追加到 `drivers/misc/Makefile` **尾部 `@@ -75,3`**。
   - 单独对干净源码 `git apply --check`：**两个都 OK**（这就是之前 dry-run "OK" 的假象）；
   - 按序号**顺序 apply**：0001 先在尾部加了 3 行，0003 的 `@@ -75` 上下文随即失效 →
     `error: patch failed: drivers/misc/Makefile:75`。
   - 附带：新文件 patch 带 `index 0000..0000` 全零行，被 patch 工具判成 reverse 而跳过文件创建。
   - **修复**：两个驱动合并成**一个** patch `0001-misc-add-rk3399-drivers.patch`，Makefile 只改一次；
     去掉全零 index 行（仿成功的 0002）；锚点从尾部 `@@ -75` 改为**头部 `@@ -1,4`**（SPDX 注释块，
     在 6.18.63/64 逐字节一致）。生成脚本 `tools/mk-board-drivers-patch.py`。

2. **armian 官方 patch 与滚动内核冲突**：
   workflow 原本 `KERNELBRANCH` 未 pin，armian 默认 `branch:linux-6.18.y` 滚动。
   成功 run #44055636949 = 6.18.63（1cdda838），失败 run = 6.18.64（fd7cfd39）；
   6.18.64 主线吸收了 CAN 的 `dev_kfree_skb_any(skb)` 修复 → armian 的 `general-can-3` patch
   变成 `Reversed (or previously applied)` → patching.py 计入 failed → 整体失败。
   patching_config.yaml **没有排除单个 patch 的机制**，无法在 userpatches 里删掉官方 patch。
   **修复**：compile.sh 显式 `KERNELBRANCH=tag:v6.18.63` pin 到已知全绿的版本（可复现）。

**编译前确认（防复发）**：
- 本地：`tools/preflight-build.sh` —— 检查 workflow 已 pin 内核版本，拉该版本内核的 patch 目标文件，
  在临时 git 树上**顺序 apply 所有 userpatches**，任一失配即非零退出、禁止 push。
  已做正例（PASS）与反例（恢复旧 0001/0003 → 准确拦截 FAIL）双测。
- CI：workflow 新增 `Preflight - verify kernel patches apply in order` 步骤，同样逻辑搬到云上，
  patch 失配立即失败，不必等第 8 分钟的编译。

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
| 6 | **Preflight（2026-11-17 新增）** | 拉 `KERNELBRANCH` pin 版本内核的 patch 目标文件，临时 git 树上**顺序 apply 所有 kernel userpatch**；失配立即失败，不等编译（§3.5） |
| 7 | Build | `./compile.sh build BOARD=rk3399-mid BRANCH=current RELEASE=noble KERNELBRANCH=tag:v6.18.63 BUILD_MINIMAL=yes KERNEL_CONFIGURE=no COMPRESS_OUTPUTIMAGE=img` —— **KERNELBRANCH 必须 pin**，否则滚动分支会让 armian 官方 patch reversed（§3.5） |
| 8 | Verify | 解 `linux-u-boot-rk3399-mid-*.deb` 看 `uboot.img`/`trust.bin` 魔数；回读镜像 LBA0/1/64/8192/16384/24576/32768 |
| 9 | PARM variant | 生成并校验 `-parm.img`（失败不阻断主产物） |
| 10 | Collect + upload | 镜像、deb、`boot-uboot.img`/`boot-trust.bin`、`rk3399-mid.dtb` |

---

## 八、构建史

| run | sha | 结果 | 说明 |
|---|---|---|---|
| #43005314503 | 1c8949c | ❌ | `trust.ini` 缺失（§3.2）——U-Boot 本体 37 s 成功，仅 `trust_merger` 失败 |
| #43009803786 | 48ca8ec | ✅ **成功** | 补 `add-trust-ini.patch` + 去掉 `DEFAULT_FDT_FILE` 覆写；11:11→13:04，约 113 min |
| #44055636949 | 19bb039 | ✅ **成功** | camera kconfig 修复（远端 camera 线终点），内核 6.18.63 |
| #44079575914 | 74a5a95 | ❌ | 3 patch 应用失败（§3.5）：0001/0003 Makefile 顺序冲突 + 6.18.64 滚动导致 armian `general-can-3` reversed |
| （修复后待触发）| 待填 | — | 合并 0001+0003 为单个 patch + 头部锚点；pin `KERNELBRANCH=tag:v6.18.63`；新增本地+CI 双层 preflight |

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

---

## 十、构建耗时分解与增量路径（2026-11-17，只记录未实施）

> 起因：一次内核改动要等 69 分钟，质疑「既然只要内核 deb，为什么每次都编整包镜像」。
> 结论：**框架原生支持只编内核**（`./compile.sh kernel`），但内核本体编译才是真瓶颈，
> 单靠换 target 只能省 20%；要压到个位数必须做 worktree 增量或干脆本地编 dtb。

### 10.1 run17 实际耗时（Actions API `/actions/runs/{id}/jobs`）

| # | 步骤 | 耗时 |
|---|---|---|
| 1–6 | setup / 3×checkout / userpatches / requirements | 1.1 min |
| **7** | **Build Armbian image** | **67.3 min** |
| 8–11 | Verify / Boot layout / Collect / upload-artifact | 0.7 min |
| 20–23 | post + complete | 0.1 min |
| | **job 总计** | **69.2 min** |

⇒ 69 分钟里 97% 集中在一个 `./compile.sh build` 调用内，其余步骤合计不到 2 分钟。
「Verify 断言」「上传 artifact」这些都不是耗时源。

### 10.2 只编内核：框架原生目标（无需改 armbian/build）

`lib/functions/cli/commands.sh` 里已注册（main 分支实测行号）：

| 行 | 注册项 | 等价变量 |
|---|---|---|
| `:74` | `["kernel"]="artifact"` | — |
| `:133` | `["kernel"]="WHAT='kernel' ${common_cli_artifact_vars}"` | `WHAT=kernel` |
| `:141` | `["kernel-dtb"]="WHAT='kernel' KERNEL_DTB_ONLY='yes' …"` | 只编 DTB |
| `:83` | `["uboot"]="artifact"` / `:145` `WHAT='uboot'` | 只编引导 |
| `:76-77` | `kernel-patch` / `kernel-config` | 交互式改补丁 / 配置 |
| `:81` | `["dts-check"]="WHAT='kernel' DTS_VALIDATE='yes' …"` | 只校验不编译 |

对应命令（BOARD/BRANCH 必给，RELEASE 只影响 deb 版本串，本板固定 noble）：

```bash
./compile.sh kernel     BOARD=rk3399-mid BRANCH=current RELEASE=noble   # → linux-image/dtb/headers 三个 deb
./compile.sh kernel-dtb BOARD=rk3399-mid BRANCH=current RELEASE=noble   # → 只产 dtb（KERNEL_DTB_ONLY=yes）
./compile.sh uboot      BOARD=rk3399-mid BRANCH=current RELEASE=noble   # → linux-u-boot-*.deb
```

`WHAT=kernel` 走 `obtain_artifact kernel` → `compile_kernel()`，**不触发** debootstrap、
不装 armbian 附属包、不组装/压缩镜像、不编 u-boot。产出的 `linux-image-current-rockchip64_*.deb`
与现在 `dist/v17/` 里那份同名同结构 ⇒ 板上 `dpkg -i` 原地升级路线完全不变。

### 10.3 能省多少（估算，未实测）

| 被砍掉的环节 | 估算耗时 |
|---|---|
| u-boot binman 编译（v2026.10 + ATF FIT） | 3–5 min |
| debootstrap noble + 装基础包 | 4–6 min |
| 镜像组装 + `COMPRESS_OUTPUTIMAGE=img` | 2–3 min |
| armbian-bsp-cli / zsh 等附属 deb | 1–2 min |
| **合计可省** | **10–16 min** |
| **kernel-only 预计** | **52–56 min（省 20%）** |

剩下 50 分钟全是内核本体：rockchip64 全量 defconfig（≈4000 个 obj）+ 267 个 armbian 补丁
+ 本板加的 ISP1/imx307/es7243，在 4 vCPU / 16 GB 的 `ubuntu-24.04` runner 上就是这么快，
**换 target 不会改变这段**。

### 10.4 三条真正能提速的路径

**路径 A：只改 DTS → 本地编 dtb，别上 CI（最高性价比）**

dtc 是 host 工具，不需要 aarch64 交叉编译器；DTS 里只用到了 `dt-bindings` 宏。

```bash
# 一次性准备（本机 macOS）
curl -L https://github.com/dgibson/dtc/archive/refs/tags/v1.7.2.tar.gz | tar xz
cd dtc-1.7.2 && make -j8 NO_PYTHON=1 NO_YAML=1        # clang 可编，不需要 brew
# 拉内核 6.18 的 dts 依赖（几 MB，只需 include/dt-bindings + rockchip 目录）
cpp -nostdinc -undef -D__DTS__ -x assembler-with-cpp \
    -I linux/include -I linux/arch/arm64/boot/dts \
    rk3399-mid.dts | dtc -I dts -O dtb -o rk3399-mid.dtb    # 约 1 s
```

板上验证：`scp` 到 `/boot/dtb/rockchip/rk3399-mid.dtb` → `systemctl reboot` →
`dmesg | grep -i <新节点>`。改 pinctrl / 加 sensor 节点 / 调 regulator 这类调试应一律走这条，
30 秒一个来回，不占 CI 额度。⚠ 前提是本机 `dtc` 与内核 `scripts/dtc` 版本差异不至于改变输出，
首次建议与 CI 产物 `dtb` 做 `dtc -I dtb -O dts` 归一化后 diff 一次。

**路径 B：改驱动/补丁 → `kernel` + 缓存内核 worktree**

armbian 官方的态度写在 `lib/functions/configuration/main-config.sh:63`：

```bash
declare -g USE_CCACHE="${USE_CCACHE:-no}"   # stop using ccache as our worktree is more effective
```

⇒ **官方推荐 worktree 增量，而不是 ccache**。需要缓存的是（`kernel-git-oras.sh:200`、`kernel.sh:11`）：

```
build/cache/sources/linux-kernel-worktree    # 内核源码树 + 上一轮 .o / .a
build/cache/git-bare/kernel                  # 完整裸库
build/cache/git-bare/shallow-kernel-6.18     # 浅克隆裸库
build/cache/git-bundles/kernel
```

GA 侧做法：`actions/cache@v4` 挂上述目录，用**滚动 key**（`key: kernel-wt-${{ github.run_id }}`
+ `restore-keys: kernel-wt-`），这样补丁集变了也能 restore 上一份做增量，而不是整份 miss。
代价：压缩后约 1.5–3 GB，首次构建照旧 50 min 且要额外花几分钟上传缓存；命中后只重编改动
目标，预计 5–15 min。风险点：armbian 的 patcher 检测到补丁 hash 变化时会 `git reset --hard`
重建工作树，此时缓存白搭但不会出错，属于「有收益无副作用」。
另可配 `CLEAN_LEVEL=` 阻止默认的 `make clean` 把 `.o` 清掉。

**路径 C：改引导 → `./compile.sh uboot`（约 5 min）**，改板级配置 + 内核 → 才需要回 `build` 出镜像。

### 10.5 本次决定

**不改 workflow**，仅记录。现有 `.github/workflows/build-armbian.yml` 仍只有
`release` / `desktop` 两个输入，第 6 步固定 `./compile.sh build`，Verify 步骤里的
U-Boot 魔数断言与镜像 LBA 断言也强依赖 `.img` 存在 —— 将来若要加 `build_target` 输入，
Verify 必须同步按 target 分支裁剪，否则 kernel-only 会卡在「output/images 下没有 .img」。

