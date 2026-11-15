# ⛔【整份判伪 · 2026-11-15】ophub 固件选型：rk3399-mid（视频会议一体机）

> ## ⛔ 判伪声明（2026-11-15 21:2x，用户核对 DRAM 丝印后确认）
> **本文的核心选型结论「选 TN3399，因为本板是 4 GB DDR3」已整体作废，不得再作为编译或刷机依据。**
> - 本板 DRAM = **4 GB LPDDR4（2ch × 2048 MB，416→856 MHz）**：① 用户现场核对 DRAM 丝印确认为 LPDDR4；② TTL 训练日志 `Channel 0/1: LPDDR4 … Size=2048MB / training pass / 856MHz`（`rescue/direct-boot/serial-captures/boot-20261114-1243-poweron.txt:24-27`、`boot-20261114-1727-readonly.txt:52-55,240-243`）。双证钉死。
> - 原厂 DTB 的 `ddr3_speed_bin=0x15` / `dmc cur_freq=800MHz` 是 **vendor BSP DMC 驱动的属性名**，RK3399 BSP 对 LPDDR3/LPDDR4 同样沿用 `ddr3_*` 命名的 `sdram-params`；属性名 ≠ 物理 DRAM 类型，且 800 MHz 与实测 416→856 MHz 不符。
> - ophub `model_database.conf` 的 `r403 TN3399 = 4GB-DDR3` 描述的是 **TN3399 这块板**，不是本板；当初「逐项吻合」是类比推断。
> - **§一 结论、§三 硬件对照表的「内存」行与「TN3399 胜出的决定性理由」、§八「不要选 rockpi4b 因为 LPDDR4」全部作废**；§七 里以 DDR3 为卖点的备选板型理由同步作废。
> - 本文 §二 / §十 / §十一～§十五 的**实测布局、坐标、PARM/GPT 冲突、IDB 与 Loader +8192 偏移**等事实与 DDR 类型无关，**继续有效**，保留作证据链。
> - **新的选型结论见本文 §十六**（2026-11-15 重选：LPDDR4 + vendor `uboot.img` LOADER 阵营），权威基线为 armbian 源码与官方 board 规范。
> - ⚠️ **22:0x 补充判定（见 `docs/引导机制判定-20261115.md`）**：§十六 选出的 r432 AIO-3399C 属 **ophub 混搭引导派**（IDB@LBA64 + `LOADER`@16384 + `BL3X`@24576 + GPT），与 armbian 官方已验证的 mainline 派（rockpi4b ≡ WF7000A：`u-boot-rockchip.bin`@64 + FIT@16384 + MBR）**并不一致**。⇒ **ophub 参照只用于 LPDDR4/8G eMMC 的硬件适配与格式交叉验证，绝不作为引导链基线**；编译基线以 armbian 官方 board 配置（`BOOT_SCENARIO` + 官方 `write_uboot_platform()` 产物分派）为准。
> - ⚠️ **阅读规则**：§一～§九 的 DDR3 结论为**历史原文保留、未逐行改写**，一律不作准（§三 对照表「内存」行、§三「TN3399 胜出的决定性理由」、§七 DDR3 备选理由、§八 排除 rockpi4b 的 LPDDR4 理由尤其如此）。完整作废清单见 §16.5。
> - ★ **22:2x 路径决策**：用户拍板**路径 1 优先**（armbian 官方 mainline + rockpi4b 写法），本文件 §十六 的 ophub 混搭布局**降级为路径 2 备案**——仅当路径 1 编译产物结构正确、排除 boot0/OTG/DTB 等外部因素后多次实刷仍失败，才考虑切换。判据与切换步骤见 `docs/引导机制判定-20261115.md` §五。

> 生成时间：2026-11-11 12:2x
> 数据源：`ophub/amlogic-s9xxx-armbian` Release `Armbian_trixie_arm64_server_2026.11`、`model_database.conf`（`r401`–`r441`）、`ophub/u-boot`、`build-armbian/.../bootfs/dtb/rockchip/` 下 50 份 rk3399 DTB 逐份解析；本板基准来自 `armbian/硬件清单-详尽版.md` 与 `docs/vendor-dtb-facts.md`。

## 一、结论（直接给答案）

**选 `TN3399` 版**：

| 项 | 值 |
|---|---|
| 文件 | `Armbian_26.11.0_rockchip_tn3399_trixie_6.18.59_server_2026.11.02.img.gz` |
| 大小 | 861,607,103 B = 821.7 MiB |
| sha256 | `f765b2e95143262cf540c915e27ad99a1c86b09cabe0b47a48aa6e946fb47dae` |
| 内核 | 6.18.59 `stable/6.18.y` |
| 系统 | Debian trixie / server / arm64 |
| 下载 | `https://github.com/ophub/amlogic-s9xxx-armbian/releases/download/Armbian_trixie_arm64_server_2026.11/Armbian_26.11.0_rockchip_tn3399_trixie_6.18.59_server_2026.11.02.img.gz` |
| 本机通道 | 直连 `github.com` 超时 → 用 `https://gh-proxy.com/<上面完整 URL>`（实测约 13 MiB/s） |

**已下载到本机并校验通过**：`rk3399-mid-backup/test/ophub-firmware/Armbian_26.11.0_rockchip_tn3399_trixie_6.18.59_server_2026.11.02.img.gz`，62 秒 / 13 MiB/s，sha256 与 Release API 给出的 digest 一致。

**⚠️ 这份镜像不能直接整盘刷**（实测布局见 §十）：它的 `LOADER` 在 LBA 16384、`BL3X` 在 LBA 24576、LBA0 是 GPT；本板 boot0 miniloader 只从 **LBA 8192** 找 `LOADER`，LBA0 必须是 `PARM`。整盘刷 = 覆盖 parameter + 清掉 LBA8192 ⇒ 起不来。必须按 §六 重排。

**但必须换 DTB**：ophub **50 份 rk3399 DTB 的 `/edp@ff970000` 全部 `status="disabled"`**，没有一份默认点亮本板 eDP 一体屏。要换成我们自己写的 `linux/rk3399-mid.dtb`。

## 二、ophub 镜像的结构事实（决定了「选哪份」到底在选什么）

1. **镜像是通用 rootfs + 全量 DTB**。本地 WF7000A 那份 ophub 镜像前 160 MiB 里扫到 **67 个 `rk3399-*.dtb`**（rockpi-4b / sapphire / pinebook-pro / gru-kevin 等） + `boot.scr` + `armbianEnv.txt` + `fdtfile=`。所以**任何一份 rockchip 镜像都能换 DTB**，改 `/boot/armbianEnv.txt` 的 `fdtfile` 即可。
2. 板型差异只有 5 处（`model_database.conf` 列定义）：`FDTFILE`、`TRUST_IMG`、`MAINLINE_UBOOT`、`BOOTLOADER_IMG`、`BOOT_CONF`。内核、rootfs、DTB 集合全部相同。
3. `r401`–`r441` 共 41 个 rk3399 板型，其中 **31 个用 `uboot.img` + `idbloader.bin` + `trust.bin`（vendor LOADER 格式）**，9 个用 `u-boot.itb` + `idbloader.img`（mainline FIT / LBA64 格式），1 个 `u-boot-rockchip.bin`。
4. **本板 boot0 miniloader 只认 `uboot.img`（LOADER 格式，写 LBA 8192）**，`u-boot.itb` 阵营（含 WF7000A 的 rockpi4b）在本板不兼容。这是选型的硬门槛。

## 三、硬件对照表

| 维度 | 本板 rk3399-mid | **TN3399 (r403)** | SW799 (r417) | ZYSJ (r410) | Fine3399 (r416) | rockpi4b（WF7000A） |
|---|---|---|---|---|---|---|
| SoC | RK3399 | RK3399 | RK3399 | RK3399 | RK3399 | RK3399 |
| 内存 | 4 GB **DDR3-1600** | **4 GB DDR3** ✅ | 4 GB DDR3 ✅ | 4 GB LPDDR3 ⚠️ | 4 GB（未标类型） | **LPDDR4** ❌ |
| eMMC | **8 GB** DG4008 HS400 | 16 GB | 16 GB | **8/128 GB** ✅ | 8–128 GB ✅ | 16 GB |
| 千兆网 | GMAC RGMII / 外置 125 MHz | 1 GbE ✅ | 1 GbE ✅ | 1 GbE ✅ | 1 GbE ✅ | 1 GbE |
| WiFi/BT | **AP6255** (BCM43455) SDIO | **AP6255** ✅（唯一明写） | 未标 | 未标 | 未标 | AP6255 |
| PMIC | RK808 + SYR827/828 | RK808 + SYR827 ✅ | RK808 | RK808 + SYR827 | RK808 | RK808 |
| 引导件 | LBA8192 `LOADER` | **`uboot.img`** ✅ | `uboot.img` ✅ | `uboot.img` ✅ | `uboot.img` ✅ | **`u-boot.itb` / LBA64** ❌ |
| eDP 面板 | ✅ 138.5 MHz + PWM0 背光 | DTB `disabled` ❌ | `disabled` ❌ | `disabled` ❌ | `disabled` ❌ | `disabled` ❌ |

**TN3399 胜出的决定性理由**：唯一同时满足「4 GB DDR3 + AP6255 + 1 GbE + eMMC + `uboot.img` LOADER 格式」的板型。DDR 类型其实不影响 U-Boot proper（DDR 由 boot0 miniloader 初始化），但它是**同一批硬件设计**的强指示；真正致命的是 rockpi4b 的 mainline `idbloader`/LPDDR4 TPL 路径，本板 boot0 根本不加载。

补充证据：
- `ophub/u-boot/u-boot/rockchip/tn3399/` = `idbloader.bin`(206,844 B) + `rk3399_loader_v1.27.126.bin`(465,230 B) + `trust.bin`(4 MiB) + `uboot.img`(4 MiB, blob sha `3d4225238fc3`)。
- 本地 `test/ophub-uboot/tn3399-uboot.img` sha256 `abaf9684…` = **U-Boot 2020.10-armbian**，`baudrate=1500000`、`console=ttyS2,1500000`，`boot.scr` / `extlinux` / `distro_bootcmd` / `booti` 齐全。
- **SW799 的 `uboot.img` 与 TN3399 sha 完全相同** ⇒ 互为备份，刷哪个引导效果一样。
- 头格式逐字段对齐：0x00 `"LOADER  "`、0x10 `load_addr=0x00200000`、0x14 size、0x18 crc、0x1c ver=32、0x20 起 32 B hash、payload @0x800 —— 与 `stock/uboot.img` 同构。

## 四、DTB 硬件打分（50 份全量解析，`tools/fdt.py`）

按 `edp / panel / backlight / rk808 / sdhci / gmac / sdio-pwrseq / goodix / es8316 / syr827` 加权：

| 排名 | DTB | 得分 | eDP 控制器 | panel | 备注 |
|---|---|---|---|---|---|
| 1 | `rk3399-zysj.dtb` | 13 | 有 | 有 | 但 `edp` = **disabled**，`backlight` = disabled；含 `lcd-panel-reset` pinctrl |
| 1 | `rk3399-firefly*.dtb` / `fine3399` / `eaidk-610` / `emb3531-old` | 13 | 有 | 有 | 同样 disabled |
| 9 | `rk3399-tvi3315a` / `tps781` / `lzk4` | 12 | 有 | — | 含 `es8316`、背光 |
| 13 | `rk3399-tn3399-v3.dtb` | 9 | 有 | — | 基础外设齐全，显示全关 |
| … | `bozz-sw799` / `smart-am40` / `hugsun-x99` / `dg3399` / `aio-3399b` | 9 | 有 | — | 基础外设齐全，显示全关 |

> 关键：**「edp 命中」多数来自 rk3399.dtsi 里的控制器定义，节点状态是 `disabled`**。逐份精确解析确认，50 份里没有任何一份 `/edp@ff970000 status="okay"`。所以显示这一项上 ophub 全军覆没，只能靠我们自己的 DTB。

本板原厂 DTB 基准：`/edp@ff970000 status="okay"`、`/edp-panel compat="simple-panel"`、`/backlight compat="pwm-backlight"`、像素时钟 138,500,000 Hz、背光 PWM0(25 µs) + `GPIO1_B5`、面板复位 `GPIO3_PA4`。

## 五、刷之前必须知道的 5 个坑

1. **不能整盘刷**。本板 LBA0 是 `PARM 82 03 00 00`（898 B），`0x1BE–0x1FF` 已被 `mtdparts` 文本占用；ophub 镜像 LBA0 是 MBR。且 mainline U-Boot 的 `rkparm`/`PARM` 解析计数为 0，只认 GPT/MBR ⇒ 整盘刷会同时毁 parameter 并让 U-Boot 扫不到 rootfs。**正确做法：保留前 16 MiB 引导区，只从 LBA 32768 起写 rootfs。**
2. **U-Boot 阶段必黑屏**。ophub U-Boot 里 `panel` / `backlight` / `drm` / `logo` / `bmp` / `rockchip_vop` 字符串计数全 0；要等内核 DRM + 我们的 DTB 加载完才亮。
3. **默认 fdtfile 要改**：`armbianEnv.txt` 里 `fdtfile=rockchip/rk3399-tn3399-v3.dtb` → 改成 `rockchip/rk3399-mid.dtb`，并把我们的 DTB 放进 `/boot/dtb/rockchip/`。
4. **U-Boot 无法自己找到 boot 分区**（不认 PARM）⇒ 需要预设 env 走绝对扇区 `mmc read` + `booti`，或接串口手动引导；env 偏移由 DT 的 `u-boot,mmc-env-offset` 指定，待验。
5. **外设缺失**：HR8833 云台、SN3732A×3 功放、ES7243×2 麦阵、Neoway 4G 无 mainline 驱动；Goodix GT9xx、ES8316、AP6255 有驱动但要改 DTS + 补 nvram。

## 六、推荐落地路径（按实测坐标重排，不是整盘刷）

1. `tools/ci/download-ophub-firmware.sh tn3399` → 自动走 gh-proxy + sha256 校验（已完成）。
2. `gunzip -k` 得到 3528 MiB `.img`（GPT，`p1 @ LBA32768` 511 MiB、`p2 @ LBA1081344` 2999 MiB）。
3. **只写 LBA 32768 起的内容**（p1 + p2，正好覆盖本板 `resource` / `kernel` / `boot` / `recovery` / `system` 等旧 Android 分区——这些正是要替换掉的），**保留本板前 16 MiB 的 LBA0 `PARM`**。
4. **引导件重定位**（关键一步，否则 boot0 找不到）：
   - 从镜像 **LBA 16384 取 4 MiB `uboot.img`**（`LOADER  ` 头）→ 写到本板 **LBA 8192**
   - 从镜像 **LBA 24576 取 4 MiB `trust.bin`**（`BL3X`）→ 写到本板 **LBA 16384**
   - 镜像 LBA 64 的 `idbloader.bin` 在本板用不上（boot0 不读 user 区 LBA64，已实测证伪）
   - 也可以直接用现成的 `test/native-uboot-bundle/native-loader-16M.img`（本板 `PARM` + `tn3399-uboot.img` + **本板原厂 `trust.img`** + 本板 DTB），只替换 LBA 8192 一块；用原厂 trust 与 boot0 更配套。
5. 挂载 p1 改 `/boot/armbianEnv.txt` 的 `fdtfile=rockchip/rk3399-mid.dtb`，并把我们的 DTB 放进 `/boot/dtb/rockchip/`（镜像自带 92 个 rk3399 DTB 名，确定是通用集合）。
6. 接 UART2 串口（3.3 V / 1500000 8N1）观察 `=>`，预设 `bootcmd` 走绝对 LBA（因为 U-Boot 不认 `PARM`，见 §五第 1、4 条）。

## 七、备选固件（同一 Release，均已取到 sha256）

| 板型 | 场景 | sha256 |
|---|---|---|
| `sw799` | 引导件与 TN3399 相同，4 GB DDR3 | `23ffcfcdc59f00283fc7bfaa635bb5a753dc7aff35c4daffd8f39aebf444bd75` |
| `zysj` | **8 GB eMMC 与本板一致**，DTB 有 `lcd-panel-reset` + `pwm-backlight` 定义，改 DTS 起点更好 | `f1338f20e186ab0aa8e9d6102f672722a5c64de7cad4a29f00050f9dcf2b15fc` |
| `fine3399` | 8 GB eMMC 可选，DTB 带背光节点 | `fad2abc13e89a3c5cfd6c29c4d9e658899b351fd0a47025d858cedeab0fff1d6` |
| `dg3399` | 4 GB DDR3，DTB 精简 | `904b7cf67098affb810ffc43917b0018e88d1fe7f3b9ea9fa678f97326a43d5f` |
| `king3399` | 4 GB DDR3，DTB 带 `backlight` | `eea1f1efbe57d9d141c7e534de0882945d087b55303c8673865792687cadd4b3` |
| `aio-3399b` | 8–64 GB eMMC / TF，但用 `u-boot.itb` **不兼容本板 boot0** | `9884bc1a14353f924c543dfcde36814d0f277427f37dc15ec3d0ff20bd97eae4` |

## 八、不要选的

- **rockpi4b（WF7000A 那份 `wf7000a-armbian-trixie-rockpi4b-a7ce6ea0.img.xz`）**：LBA64 是 mainline TPL，内嵌 `lpddr4_set_ctl` / `LPDDR4 MR22 Soc ODT`，靠 DTB 初始化 LPDDR4；本板实测 `dmc=800 MHz` = DDR3-1600。且 LBA0 是 MBR 会覆盖 `PARM`。**已实测排除**。

## 九、相关文件

| 文件 | 说明 |
|---|---|
| `rk3399-mid-backup/tools/ci/download-ophub-firmware.sh` | 一键下载 + sha256 校验；**2026-11-15 改写为只下载 LPDDR4 参照板型**，默认 `aio-3399c` / 6.18.63 |
| `rk3399-mid-backup/test/ophub-firmware/Armbian_26.11.0_rockchip_aio-3399c_trixie_6.18.63_server_2026.11.14.img.gz` | **新参照固件**（§16.3），下载中 |
| ⛔ `test/ophub-uboot/tn3399-uboot.img`、`test/ophub-firmware/tn3399*`、`test/native-*-16M.img` 等 13 个文件 | **2026-11-15 已判伪清理**，移入 `/Volumes/HDD/.Trashes/502/rk3399-mid-DDR3判伪清理-20261115/`（可完整恢复）。下方 §十一～§十五 提到这些路径处按「历史记录」读，不再是可用的现成件 |
| `test/native-uboot-bundle/trust.img` | **保留**（sha `99bcacc6…` == 本板 `stock/trust.img`，原厂 4 段 `f8000400`），非 DDR3 产物 |
| `rk3399-mid-linux/linux/rk3399-mid.dtb` | 本板 mainline DTB（eDP 138.5 MHz / PWM0 / GPIO1_B5） |
| `rk3399-mid-linux/tools/fdt.py` | 纯 Python FDT 解析器（本机无 dtc） |
| `/tmp/ophub-dtb/` | 50 份 ophub rk3399 DTB 副本，供后续比对 |

## 十、★ 下载镜像实测布局（流式解出前 160 MiB 解析）

| 项 | tn3399 固件 | 本板 Android（parameter.txt） |
|---|---|---|
| LBA 0 | 全零 + `55aa`，p1 type=`0xee` **GPT 保护性 MBR** | `PARM 82 03 00 00`（898 B parameter 文本） |
| LBA 1 | `EFI PART` GPT 头，backup LBA 7225343 | parameter 文本延续 |
| LBA 64 | `3b 8c dc fc …` = `idbloader.bin`（DDR bin） | **全零** |
| **LBA 8192** | **全零** | **`LOADER  ` = vendor U-Boot 2014.10** |
| **LBA 16384** | **`LOADER  ` = mainline U-Boot 2020.10** | **`BL3X` = 原厂 trust/ATF** |
| **LBA 24576** | **`BL3X` = ophub trust.bin** | `misc`（BCB） |
| LBA 32768 | 全零（GPT p1 起点，511 MiB） | `RSCE` = resource.img |
| GPT p1 | first LBA **32768**，last 1079295，511 MiB | — |
| GPT p2 | first LBA **1081344**（528 MiB），last 7223295，2999 MiB | — |
| 镜像总长 | 7,225,343 扇区 = **3528 MiB** | 15,273,600 扇区 = 7457 MiB |

另：`LOADER  ` 魔数在 LBA 16384 / 18432 / 20480 / 22528 各出现一次（4 MiB 镜像内部），`BL3X` 在 24576 / 28672 出现；前 160 MiB 内扫到 **92 个 `rk3399-*.dtb` 名**（含 `rk3399-tn3399-v3.dtb` 与 `rk3399-tn3399.dtb`）、`boot.scr` 15 次、`armbianEnv.txt` 7 次、`fdtfile=` 5 次、`extlinux` 34 次、`rk3399-mid` 0 次（需自行放入）。

⇒ **坐标错位是整盘刷必失败的根因**，也解释了为什么之前 16 MiB 实验里「清了 LBA8192 后设备静默」。§六 的重排方案就是针对这一点。

## 十一、★ 2026-11-11 实刷记录与修正（第一版 → 修正版 B）

### 11.1 触发方式纠正（用户纠正，此前全部「短接」表述作废）

**RK3399 进 MaskROM 靠板载微动开关（按键），不是短接 eMMC CLK；短接方案属于 S905 系列。**
本板有电池 ⇒ 只拔适配器不彻底；彻底断电须**拔电池排线**或长按电源键放电。
正确动作：按住微动开关上电 → 进 MaskROM → 刷完松开按键 + 拔电池冷启动 → 正常引导。
此前把「`rd` 后仍停在 MaskROM」归因为「短接未松开」，实际应为「微动开关未松开／未彻底冷启动」。

### 11.2 第一版实刷（13:24 写入，13:33 `rd`）

- 13:24:30 轮询抓到真 MaskROM，13:24:41 一次 `wl 0` 写完 3.4 GiB，13:29:07 抽验 **9 一致 / 0 不一致**。
- 13:33 执行一次 `rd`（`Reset Device OK.`），此后 90 s + 60 s 两轮只读观察：**全程 `0x330c Maskrom`**，无 adb / 无 ping / ARP 无板子 MAC `24:97:ed:0b:59:71`。
- 未再执行任何 `rd` / `db` / `wl`；`rd` 不写 eMMC，固件应仍在盘上。

### 11.3 新发现：`PARM` 跨扇区占用 LBA1，与 GPT 头不可共存

| 事实 | 数据 |
|---|---|
| 全量备份 LBA0 头 | `50 41 52 4d 82 03 00 00` = magic `PARM` + 长度 **898 B** |
| 898 B > 512 B | ⇒ 占 LBA0 **整扇区** + LBA1 前 386 B |
| LBA1 实测 | parameter 文本续 `),0x00002000@0x00006000(misc),0x00008000@…`（394 个可打印字符） |
| ophub GPT 头 | `EFI PART` **必须**在 LBA1 |

⇒ 13:33 建议的「LBA0 留 PARM + LBA1 写 GPT 头」会**截断 PARM 的分区表字符串**；若 boot0 读完整 898 B 即失败。**该方案作废**。
另需记住：boot0 / miniloader 位于 eMMC **boot0 硬件分区（4 MiB）**，历次 `wl 0` 只写 user 区、从未改动 ⇒ boot0 本身完好；LBA0 是否 `PARM` 影响的是「BootROM 是否认为存储可引导」，不是 boot0 损坏。

### 11.4 修正版 B（已生成，未刷；只改一个变量）

| 坐标 | 第一版 | 修正版 B |
|---|---|---|
| LBA 0 | GPT 保护 MBR（全零 + `55aa`） | 不变 |
| LBA 1 | `EFI PART` GPT 头 | 不变 |
| LBA 64 | ophub `idbloader.bin` | 不变 |
| **LBA 8192** | ophub `LOADER`（mainline U-Boot 2020.10） | 不变 |
| **LBA 16384** | ophub `BL3X` … `ec 00 03 00` | **本板原厂 `stock/trust.img` `BL3X` … `f8 00 04 00`** |
| LBA 24576 | ophub `BL3X` 原件 | 不变（本板 boot0 不读此处） |
| LBA 32768+ | GPT p1/p2 rootfs | 不变 |
| DTB / `armbianEnv.txt` / `fdtfile` | 原样 | 原样 |

依据：`tools/ci/pack-native-uboot.sh` 既定结论 —— 本板 boot0 miniloader 必须配原厂 `trust.img`；ophub `trust.bin` 是给 mainline idbloader+SPL 组合用的，不配套。

产物：`rk3399-mid-backup/test/ophub-firmware/tn3399-fixB-stocktrust-nodtb.img`，3,699,376,128 B，sha256 `af167b4a2b438b24e3142d847a50971dbdb16e054924a4ec43ded246a07bca40`（APFS clone 生成，零额外占用）。
校验：① LBA16384 起 4 MiB 逐字节 == 原厂 trust.img；② 前 16 MiB 仅 1992 个扇区变化、全部落在 16384..24575（trust 后半段零填充属正常）；③ rootfs/GPT 抽样 8 点与第一版一致；④ `fdtfile=rockchip/rk3399-orangepi.dtb` 原样 ⇒ **未换 DTB**。

### 11.5 执行顺序（用户 13:43 决定）

1. **先回退完整 Android 全盘备份**验证板子可救回 → `tools/ci/flash-android-rescue-noreboot.sh`（一次 `wl 0` 7.2 GiB、抽验 14 点、**不 `rd` 不自动重启**）。
2. 拔电池冷启动、**不按微动开关**上电 → 确认 Android 正常起来（证明 boot0 与 eMMC 完好）。
3. 再刷修正版 B，仍不换 DTB；刷后同样拔电池冷启动、不按键。
4. 若仍落 MaskROM ⇒ 才考虑 PARM/GPT 混合（需先证实 boot0 只读 PARM 首扇区）或改 U-Boot `bootcmd` 用固定 LBA 加载、绕开 GPT 分区发现。

## 十二、★ 14:05–14:18 根因定位：BootROM 层首级 IDB 缺失（与固件镜像无关）

用户确认**所有微动开关均断开**，但设备仍是 `0x330c Maskrom` ⇒ 进 MaskROM 是 BootROM 判定「无可引导介质」，不是按键强制。

### 12.1 证据链（`db` 只把 DDR loader 下到 RAM，全程未写 eMMC）

| 检查 | 结果 | 判定 |
|---|---|---|
| `rid` / `rfi` | `EMMC ` / SAMSUNG **7457 MB、15,273,600 扇区** | eMMC 硬件完好，与全量备份一致 |
| `rci` / `rcb` / `td` | `C033…` / Direct LBA + First 4m Access + Read IDB Config 全 enabled / `Test Device OK.` | SoC、DDR、miniloader 通信全正常 |
| `rl 0 32768`（16 MiB 全扫） | `PARM`×8 @ 0/1024/…/7168；`LOADER`×8 @ 8192/8972/…；`BL3X` @16384/20480；`RSCE` @32768；`ANDROID!` @114688 | user 区是完整原厂，内容无误 |
| 同上扫描 | `EFI PART`、`0FF0AA55`、`RKNS`、`RKAF` **全 0 命中**；`rl 64` 全零 | **user 区根本没有 IDB** |
| `ppt` | `Not found any partition table!` | **假信号**：源码 `main.cpp:2105` `print_parameter()` 固定读 **LBA 0x2000=8192** 找 `PARM`，本板 parameter 在 **LBA0** ⇒ 工具找错位置 |
| `db` + 一次 `rd` | 14:16–14:18 **22/22 仍 `0x330c`**，adb/ping/ARP 全 0 | 软复位也绕不过 ⇒ 非复位姿势、非按键、非 user 区内容 |
| 历史日志全扫 | **从未执行 `ul`/`ef`/`gpt`/`prm`/`cs`** | 无人为改过 boot 分区配置 |

### 12.2 结论

按 11-10 已确立判据（「始终未出现 `0x330c` ⇒ boot0 miniloader 正常」），现在反过来 ⇒ **失败点在 BootROM 加载首级 IDB 之前**，user 区的 `PARM`/`LOADER`/`trust` 压根还没被读到。本板 idbloader 位于 **eMMC boot0/boot1 硬件分区（各 4 MiB）**，而 `rl`/`wl` 只操作 user 区 ⇒ **11-10 的全量备份从未覆盖 boot0、也从未恢复过它**（11-10 记忆已标注「唯一缺口」）。若 `PARTITION_CONFIG`（EXT_CSD[179]）此刻指向 user area，LBA64 全零同样必然失败。最可能的触发是 10:19–10:22 八次上线/离线与反复异常断电，或 DDR loader 初始化 eMMC 时持久改写 EXT_CSD。

⇒ **13:33（TN3399）与 13:58（原厂 Android）两次落 MaskROM 都不能作为任何固件方案的失败证据**；在 boot0/PARTITION_CONFIG 修好前，刷任何镜像都无意义。

### 12.3 工具边界与修复路径

- 源码 `main.cpp:2004`：`ul` = `RKU_WriteLBA(64, dwSectorNum, pIDBData)` ⇒ **只写 user 区 LBA64，够不到 eMMC boot0 硬件分区**；`upgrade_loader()` 要求 `RKUSB_MASKROM`（当前正是）。
- `rk3399_loader_v1.30.130.bin` 454,990 B ≈ 889 扇区 ⇒ `ul` 约写 LBA64..953，**不碰 LBA0 主 PARM，也不碰 LBA1024+ 的 PARM 备份**，且全量备份完好可回退。
- 顺序：① `ul` 重建 user 区 IDB（若 BootROM 已 fallback 到 user area 即可救回，同时也是确诊实验，需用户授权写操作）；② 无效则须恢复 eMMC boot0 硬件分区并设 `PARTITION_CONFIG`，本工具做不到，需 Windows RKDevTool、能跑 `mmc bootpart enable` 的 Linux 环境，或从同型号板 dump boot0；③ 引导链恢复后才继续 §11.4 修正版 B。

## 十三、★ 14:22–14:40 执行 `ul`：首级 IDB 恢复成功（MaskROM → Loader）

### 13.1 关键前提：纯 MaskROM 下 `ul` 必然失败

- 第一次 `ul`（14:25，设备标注 `Maskrom`）→ `Upgrading loader failed!`，rc=1。源码 `RKComm.cpp:691` `RKU_WriteLBA()` 发 `WRITE_LBA` CBW，**BootROM 未初始化 eMMC，CSW status=1 拒绝写入**。
- **必须先 `db <loader>` 把 DDR loader 下到 RAM 完成 eMMC 初始化**。`db` 后 `ld` 仍标注 `Maskrom`（PID `0x330c` 不变），`ul` 的 `check_device_type(RKUSB_MASKROM)` 仍通过，此时 `WRITE_LBA` 成功。
- 14:28 `db` + `ul` → `Upgrading loader succeeded.` rc=0。⇒ **`db` 是 `ul` 的隐藏前置条件**，工具帮助与源码都没写。

### 13.2 写入范围与校验

- 实测写入 **460 扇区 / LBA64..523**（不是先前估算的 889 扇区）：`dwSectorNum = 4 + align(FlashData,2048)/512 + align(FlashBoot,2048)/512`，老式 `BOOT` 格式 loader 无 `FlashHead`。
- 逐扇区比对写入前基准（从全量备份提取的 `rescue/pre-ul-lba0-2047-20261111.bin`）：变化 460 个扇区、连续、恰为 LBA64..523；**LBA0 主 `PARM`、LBA1024 起 8 份 PARM 备份全部未变**。
- 产物：`rescue/idb-lba64-460sec-20261111.bin`（235,520 B，sha `95f989e6…`）、`rescue/post-ul-lba0-2047-20261111.bin`；脚本 `tools/ci/restore-idb.sh`（`db → ul → 460 扇区 cmp → 不复位`）。

### 13.3 引导结果：前进一层，但停在 rockusb

- 一次 `rd` 后 66s 观察：21/22 采样仍 `0x330c`，但**末态 `ld` 标注由 `Maskrom` 变为 `Loader`** ⇒ BootROM 已从 user LBA64 加载 IDB 并跑起 miniloader，**首级引导链恢复**。
- 45s 静默（不向 USB 发任何命令）后仍 `Loader`；`rci`/`rid`/`rfi` 全正常；adb=0、`ping 10.26.88.129`=0、ARP 无板子 MAC ⇒ miniloader 停在 rockusb 下载模式，未继续跳 vendor U-Boot。
- 推断：`rk3399_loader_v1.30.130.bin` 是刷机用 DDR loader，其 FlashBoot 在 USB host 在线时优先进 rockusb；需**物理拔掉 USB 数据线冷启动**验证能否继续引导。

### 13.4 ★★ 陷阱：`rd` 后 LBA 视图整体偏移 8192 扇区

复位进 Loader 模式后，`rl`/`wl` 的**逻辑 LBA x 对应物理 user LBA x+8192**（4 MiB 引导区被跳过）。决定性证据：

| 逻辑 LBA | 读回 | 对照物理 user LBA | 内容 |
|---|---|---|---|
| 0 | `LOADER  ` | 8192 | `LOADER  ` ✓ |
| 8192 | `BL3X … f8 00 04 00` | 16384 | 同 ✓ |
| 16384 | 全零 | 24576 | 同 ✓ |
| 32768 | `f8f8f8…` | 40960 | 同 ✓ |
| 106496 | `ANDROID!` | 114688 | 同 ✓ |

⇒ **eMMC user 区一个字节都没被改写**，复位后「前 1 MiB 有 815 扇区变化」是坐标系假象；7.2 GiB 全量备份与 14/14 校验结果依然有效。

⇒ **后续纪律**：整盘 `wl 0 <image>` 前必须确认 `ld` 标注为 `Maskrom`（`db` 后）。若已是 `Loader`，`wl 0` 会写到物理 LBA8192、破坏原厂布局；必要时先 `rd 3` 回 MaskROM 再 `db`。

⇒ **任何整盘 `wl 0` 都会清掉 LBA64 的 IDB**，刷完必须重跑 `restore-idb.sh`，否则又回 MaskROM —— 这正是 13:33 / 13:58 两次「刷完即 MaskROM」的直接原因（当时 user LBA64 为全零/被 ophub idbloader 覆盖）。

### 13.5 下一步

1. 物理**拔掉 USB 数据线** + 彻底断电（拔电池）冷启动，观察 Android 是否起来。
2. 若仍停 rockusb ⇒ 需把**原厂 idbloader / miniloader** 写入 eMMC boot0 硬件分区并设 `PARTITION_CONFIG`（rkdeveloptool 做不到），或从同型号板 dump boot0。项目 `stock/` 目前只有 `uboot.img`(vendor `LOADER`) 与 `trust.img`(`BL3X`)，**缺 miniloader**。
3. 引导链恢复前不刷 TN3399 修正版 B。

## 十四、14:45–14:47 断电重启后复判：仍停 `Loader`，且定位到 user-IDB 方案的结构性缺陷

**只读观察（20/20 采样）**：`ld` 全程 `0x2207:0x330c` **标注 `Loader`**（不再是 `Maskrom`），adb=0、`ping 10.26.88.129`=0、ARP 无板子 MAC、无新增 ARP。`system_profiler` 仍列出 `0x2207:0x330c` ⇒ **USB 数据线仍连着主机**，本次重启未隔离「USB host 在线」变量。

**Loader 模式能力位变化**：

| 检查 | 14:05（`db` 后 Maskrom） | 14:45（`ul` 写入并复位后 Loader） |
|---|---|---|
| `rcb` | `3F 06 …` Direct LBA / Vendor Storage / **First 4m Access** / Read LBA / Read IDB Config 全 enabled | `28 04 …` 仅 **Read LBA + Read IDB Config** |
| `ppt` | `Not found any partition table!` | 同样失败 |
| `td` | `Test Device OK.` | `Test Device OK.` |

⇒ 当前运行的是 `ul` 写入的**刷机用 DDR loader 内的 miniloader**，能力比原厂 boot0 idbloader 少，且全命令表（`ld/db/ul/rl/wl/wlx/gpt/prm/ppt/ef/td/rd/cs/rid/rfi/rci/rcb/pack/unpack/tagspl`）**没有读写 eMMC boot0/boot1 硬件分区的入口**；`cs` 只切存储介质（EMMC/SD/SPINOR），RW_SUBCODE 也只有 IMAGE/LBA 两种，与 boot 分区无关。

**★ 结构性缺陷（强推论，待拔线冷启动验证）**：IDB 放在 **user 区 LBA64** 时，设备把介质前 4 MiB 当作引导区跳过 ⇒ `rl`/`wl`/`ppt` 的逻辑 LBA0 = 物理 8192（§13.4 五点实证）。于是 **`PARM` 位于物理 LBA0，对当前 miniloader 不可见**（`ppt` 固定读逻辑 8192 = 物理 16384 = `BL3X`，必然找不到）。miniloader 读不到分区表 ⇒ 无法定位 `uboot`/`trust` ⇒ 停 rockusb。

⇒ **`ul` 写 user LBA64 只能把设备从「无介质 MaskROM」变成「可刷机 Loader 状态」，不能完成正常启动链**；这也解释了 13:33 / 13:58 之前所有「刷完即 MaskROM」。要真正启动，必须让 IDB 位于 **eMMC boot0 硬件分区**（不占用 user 区坐标）并设 `PARTITION_CONFIG`(EXT_CSD[179]) 指向 boot0，或从原厂 update.img 解出 `MiniLoaderAll.bin` / `rk3399_miniloader_*.bin` + `rk3399_ddr_*.bin` 重新打包。项目 `stock/` 只有 `uboot.img`(vendor `LOADER`) 与 `trust.img`(`BL3X`)，**缺 miniloader**。

**下一步**：① 物理拔 USB 数据线 + 拔电池彻底冷启动（等 30s 后再插 USB 观察），排除 host 在线触发下载模式；② 若仍 rockusb ⇒ 上述推论坐实，转「写 eMMC boot0 硬件分区」路线（Windows RKDevTool / 能跑 `mmc bootpart enable` 的 Linux 环境 / 同型号板 dump boot0）；③ 在此之前不刷任何整盘镜像。

## 十五、★ 15:00–15:20 用户「重刷一遍 Android」+「不要切回 MaskROM」→ 4 MiB 补偿镜像一次刷完

### 15.1 用户纠正与日志核对

用户明确：**不要切回 MaskROM，之前在 loader 刷安卓是成功的** ⇒ 本轮全程保持 `ld` 标注 `Loader`，**未执行 `rd 3` / `rd` / `db`**。

日志核对：09:56 与 13:47 两次成功整盘刷写的 `ld` 行都是 `DevNo=1 … 0x330c … Maskrom`，且都先 `db`；用户所说的「loader」应指 `0x330c` 下载模式这一泛称。但按用户指令不切换模式。另注：当前 Loader 下 `db` 会被拒（`The device does not support this operation!`），不能靠 `db` 回到物理坐标系。

### 15.2 1 扇区可逆探针：`wl` 与 `rl` 共用偏移坐标系

| 步骤 | 结果 |
|---|---|
| 读逻辑 LBA0 原值 | `4c4f414445522020`（= 物理 8192 的 `LOADER`）；物理 LBA0 原值（取自备份）= `5041524d82030000`（`PARM`） |
| 写 512B 探针到逻辑 LBA0 | `wl 0` rc=0 |
| `rl 0` 读回 | `524b50524f42452d`（探针模式）⇒ **`wl` 也偏移 8192**，`log/WL-COORD-MODE=SHIFTED` |
| 立即写回原扇区 | `rl 0` 恢复 `4c4f414445522020`，探针完全可逆、无残留 |

⇒ 直接 `wl 0 <原厂镜像>` 会把 15,273,600 扇区写到物理 8192 起并越界，**绝对不可**。

### 15.3 4 MiB 补偿镜像（不切模式的正解）

`shifted[j] = orig[j+8192]`，j = 0..15,265,407；大小 **7,815,888,896 B / 15,265,408 扇区**，sha `dee6220959bac626b81d6f232b14c8fe48a9b84003073c4cee20b1799ff0dc98`。

`wl 0 shifted` 把 shifted[j] 写到物理 LBA j+8192 ⇒ 物理 LBA i (i≥8192) == orig[i]。写入终点 = 8192+15,265,408-1 = **15,273,599**，正好 eMMC 最后一扇区，不越界。物理 LBA0..8191 **完全不写** ⇒ `PARM` 主份、8 份参数备份、`ul` 写入的 IDB（物理 LBA64..523）全部原样保留，**刷完无需再跑 `restore-idb.sh`**。

产物：`rescue/android-shifted-4M-for-loader-20261111.img`；脚本 `tools/ci/flash-android-loader-shifted.sh`（设备检查 → 坐标系复核 `rl 0 == 4c4f414445522020` → 一次 `wl 0` → 14 点抽验 → 不复位）。抽样 10/10 PASS（含 shifted[106496]=orig[114688]=`ANDROID!`、尾扇区）；完整 `cmp` 因 HDD 双 7.2G 对读 5 分钟超时被终止，改用抽样 + `dd` records 数/大小/sha 三重确认。

### 15.4 执行结果

| 时刻 | 事件 |
|---|---|
| 15:10:25 | 脚本启动，设备 `Loader`，坐标系复核 PASS |
| 15:11:16 | 开始一次 `wl 0` 写入 7,815,888,896 B |
| 15:19:44 | 写入 100% 成功，耗时 8m28s |
| 15:20:30 | **抽验 14 一致 / 0 不一致** |

**未 `rd`、未切 MaskROM、未 `db`、未重启**，无残留进程。设备仍 `0x330c Loader`。日志 `log/android-loader-shifted-20261111-151025.log`。

### 15.5 顺带澄清一处旧误判

抽验点 `shifted[64] = orig[8256] = e1031caae00315aa`，与 14:33 在 Loader 视图下读逻辑 LBA64 的值**完全一致** ⇒ 再次反证 §13.4：当时以为「复位后 LBA64 被 miniloader 改写」是**坐标系假象**，物理 LBA64 的 IDB 从未被改写，一直完好。

### 15.6 下一步

断电（拔电池）冷启动验证 Android 是否起来。**注意：本次重刷只重写 user 区，未改 eMMC boot0 硬件分区 / `PARTITION_CONFIG`** ⇒ 若 §十四 的推论成立，仍会停在 rockusb；届时转「写 boot0」路线。

---

## 十六、★ 2026-11-15 重选 ophub 参照（DDR 判伪后的权威替换）

> 用户指令：**mid 不与 WF7000A 保持一致；编译以 armbian 源码 + 官方 board 规范为基线；重新选 ophub 更相近的固件做参照。**
> 数据源（本轮实拉，非二手推断）：`https://raw.githubusercontent.com/ophub/amlogic-s9xxx-armbian/main/build-armbian/armbian-files/common-files/etc/model_database.conf`（479 行，RK3399 Family 在 347–407 行）+ Release `Armbian_trixie_arm64_server_2026.11` 的 461 个 asset。

### 16.1 筛选判据（优先级从高到低）

1. **DRAM = LPDDR4**（本板已钉死）；
2. **引导阵营 = vendor `uboot.img`(LOADER) + `idbloader.bin` + `trust.bin`**，而非 `u-boot.itb`/`idbloader.img` 的 mainline FIT 阵营（后者正是 WF7000A/rockpi4b 走的路线，用户已明确不与之对齐）；
3. eMMC 容量 / 4 GB 内存 / 1 GbE 尽量贴近；
4. `BOOT_CONF` 尽量与 armbian 官方 `armbianEnv.txt` 一致，便于对齐官方规范。

### 16.2 RK3399 家族里明确标 LPDDR4 的板型（原文摘录）

| ID | 板型 | model_database 描述 | 引导阵营 | 判定 |
|---|---|---|---|---|
| **r432** | **AIO-3399C** | `2GB/4GB-LPDDR4,8G/128G-eMMC,SD,1Gb-Nic` | `trust.bin` + `uboot.img` + `idbloader.bin` | ✅ **主选**：LPDDR4 + **8G eMMC 与本板一致** + vendor LOADER 阵营 |
| r433 | AIO-3399C(AI) | `2GB/4GB-LPDDR4,8G/128G-eMMC,SD,1Gb-Nic` | 同 r432 | 备选（r432 的 AI 变体） |
| **r441** | **AI3399-C** | `4GB-LPDDR4,32G-eMMC,TF,1Gb-Nic` | `trust.bin` + `uboot.img` + `idbloader.bin`，`armbianEnv.txt` | ✅ **次选**：4 GB LPDDR4 明写 + BOOT_CONF 与官方一致 |
| r430 | NanoPC-T4 | `4GB-RAM,64G-eMMC,1Gb-Nic`（硬件实为 LPDDR4，库里未明写） | 同 vendor 阵营 | 备选（类型靠外部资料，不如 r432/r441 硬） |
| r413 | Leez-P710 | `4GB-LPDDR4,16G-eMMC,1Gb-Nic` | **`u-boot.itb` + `idbloader.img`** | ❌ mainline 阵营，与 WF7000A 同路，排除 |
| ~~r403~~ | ~~TN3399~~ | ~~`4GB-DDR3,16G-eMMC,…`~~ | vendor 阵营 | ⛔ **旧参照作废**（DDR3 板，选型理由不成立） |

### 16.3 主选参照的可下载镜像（已取到 digest）

| 项 | 值 |
|---|---|
| 文件 | `Armbian_26.11.0_rockchip_aio-3399c_trixie_6.18.63_server_2026.11.14.img.gz` |
| 大小 / sha256 | 863,302,087 B / `64d42550bb20d6640342603de9e6d9b20b0dac587b15a8244799b00e092a61df` |
| 内核 | 6.18.63 —— **与本项目 CI 产出的 `6.18.63` 完全一致**，便于逐段对照 |
| 通道 | `https://gh-proxy.com/https://github.com/ophub/amlogic-s9xxx-armbian/releases/download/Armbian_trixie_arm64_server_2026.11/<文件名>` |

次选：`Armbian_26.11.0_rockchip_ai3399-c_trixie_6.18.63_server_2026.11.14.img.gz`，862,583,756 B，sha256 `ed9b2292cb16eb335f966772b6862ffc89fc3018a3f1e027c795981f42e996d7`。

### 16.4 参照物用在哪、不用在哪

- **用**：对照 `idbloader.bin` / `uboot.img` / `trust.bin` 三件的**格式与落盘坐标**、LBA0 分区表形态、`armbianEnv.txt` / `extlinux.conf` 的 bootargs 结构、DTB 集合里 eDP/背光/GMAC 的写法，作为「armbian 官方规范产出的板级镜像」的实物参照。
- **不用**：**不整盘刷、不照抄其 DTB、不把它的坐标当成 mid 的坐标**。本板实测坐标仍是 §十 / §十三～§十五 的 `LBA0 PARM + LBA8192 LOADER + LBA16384 BL3X`，rootfs 起点 LBA32768；这与 ophub 的 `LBA0 GPT + LBA64 idbloader + LBA16384 LOADER + LBA24576 BL3X` 不同，必须重排。
- **编译基线不变**：`armbian/build` 官方源码 + `userpatches/config/boards/rk3399-mid.csc`（`BOARDFAMILY=rockchip64` / `BOOT_SCENARIO=only-blobs` / `BOOTCONFIG=evb-rk3399_defconfig`），ophub 镜像只作**参照与交叉验证**，不进入构建链。

### 16.5 连带作废清单（与 DDR3 相关的旧结论）

| 旧结论 | 处置 |
|---|---|
| 「本板 4 GB DDR3-1600 / dmc 800 MHz」 | ⛔ 作废，改 **4 GB LPDDR4 416→856 MHz** |
| 「U-Boot 必须用 `rk3399-sdram-ddr3-800.dtsi` 的 DDR3-800 参数」 | ⛔ 整条作废，本板 DDR 由 rkbin DDR blob 初始化，Armbian 侧不碰 `sdram-params` |
| 「选 TN3399 因同为 DDR3」 | ⛔ 作废，改 §16.2 的 LPDDR4 判据 |
| 「WF7000A 的 LPDDR4 idbloader 在 DDR3 板上假死 ⇒ 不通用」 | ⛔ **排除理由作废**（本板正是 LPDDR4）；但「不与 WF7000A 对齐」由用户指令确立，属路线选择而非硬件不兼容 |
| 「`rk3399_ddr_800MHz_v1.30.bin` 是 DDR3-800 专用」 | ⛔ 作废，`800MHz` 只是 rkbin 版本/频率档标签，内含多套训练表，TTL 实证在 LPDDR4 上 training pass |

