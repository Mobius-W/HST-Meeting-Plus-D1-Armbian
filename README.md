# HST Meeting Plus D1 Armbian

> **RK3399 会议平板（HST Meeting Plus D1）从原厂 Android 到 Armbian 的完整移植。**
> 目标：任何人按本仓库的代码与文档，可以从 0 把一台原厂机器刷到本项目当前的软件状态。

| 项 | 值 |
|---|---|
| 设备 | HST Meeting Plus D1（Rockchip Sapphire + Excavator 参考设计的定制会议平板） |
| SoC | RK3399，2×Cortex-A72 + 4×Cortex-A53，Mali-T860 MP4 |
| 内存 / 存储 | 4 GB LPDDR4（2ch×2048 MB）/ 8 GB eMMC（DG4008） |
| 目标系统 | Armbian noble，内核 `6.18.63-current-rockchip64`（mainline） |
| 原厂系统 | Android（完整备份见 [`firmware/android-stock/`](firmware/android-stock/)） |
| 编译方式 | GitHub Actions 云端编译，本地不需要交叉工具链 |
| 仓库状态 | 公开 |

---

## 1. 项目目标

把 HST Meeting Plus D1 从原厂 Android 适配为 Armbian（mainline Linux），做到：

1. **能刷**——给出从原厂状态进入 Loader / MaskROM、下 loader、写盘、冷启动的完整命令链；
2. **能跑**——eDP/HDMI 显示、触摸、音频播放与录音、WiFi/BT、网卡、风扇、电量计全部实测可用；
3. **能追溯**——每个板上器件的型号、I²C 地址、驱动状态、实测证据都写进硬件清单，结论有证据链；
4. **能复现**——DTS、内核补丁、板级配置、树外驱动、测试脚本全部在仓库里，CI 一键重建镜像。

不做的事：不精简原厂系统、不移植 Android 应用、不改动 boot0 硬件分区。

---

## 2. 硬件清单（在板器件与 Armbian 驱动状态）

状态符号：✅ 实测可用　🟡 部分可用　❌ 无驱动/无硬件　🔴 硬件故障

### 2.1 SoC / 内存 / 存储

| 器件 | 型号 / 参数 | Armbian 状态 | 说明 |
|---|---|---|---|
| SoC | RK3399（2×A72 + 4×A53，Mali-T860 MP4） | ✅ | 6 核在线，官方 `rock-pi-4` defconfig |
| 内存 | 4 GB LPDDR4（2ch×2048 MB，416→856 MHz） | ✅ | 丝印 + TTL 训练日志双证；**不是 DDR3** |
| eMMC | DG4008 8 GB HS400 ES | ✅ | `mmcblk1` 7.3 GiB |
| SD 卡槽 | `sdhci mmc0` | ❌ | 实物无卡槽，DTS 应 disabled |
| ZRAM | — | ✅ | zram0 1.9 G swap / zram1 50 M `/var/log` |

### 2.2 电源 / 电池 / 散热

| 器件 | 型号 / 地址 | 状态 | 说明 |
|---|---|---|---|
| 主 PMIC | RK808 @ i2c0 `0x1b` | ✅ | 12 路 regulator，全部 enabled |
| 大核 DCDC | SYR827 `0x40` / SYR828 `0x41` | ✅ | `fan53555-regulator` |
| 电量计 | CW2015 @ i2c4 `0x62` | ✅ | 电压分压未补偿，`voltage_now` 为实际值一半 |
| 充电管理 | `gpio-charger`（GPIO1_A7 / GPIO1_C7） | ✅ | 原厂极性 ACTIVE_LOW |
| NTC 温控 | SARADC ch0 + GPIO1_A4 | 🟡 | mainline 无专用驱动，充电回路实测正常 |
| 风扇 | `gpio-fan` | ✅ | `fan1_input=3000` |
| 温度 | `tsadc@ff260000` | ✅ | cpu/gpu 温度与 trip 点正常 |

### 2.3 显示 / 输入

| 器件 | 型号 / 地址 | 状态 | 说明 |
|---|---|---|---|
| 内屏 eDP | 11.6″ 1920×1080@60，`neweast,wjfh116008a` | ✅ | VOPL / `fb0` |
| 背光 | PWM0 + GPIO1_B5 | ✅ | 255 级 |
| miniHDMI | `dwhdmi-rockchip` HDMI 2.0 TX | ✅ | VOPB，实测最大 1920×1080（依赖 sink EDID） |
| HDMI 热插拔 | CRTC 锁定 | ✅ | 拔线后 eDP 不挂死 |
| 触摸屏 | Goodix GT9271 @ i2c2 `0x14` | ✅ | 10 点，整屏覆盖，20 s 静置 0 误触 |
| 实体按键 | 仅电源键（PMIC RK808 PWRON） | ✅ | `adc-keys`/`gpio-keys` 为参考设计残留，应 disabled |
| 电源键 LED | 硬件直驱 | ✅ | 上电即亮，不受软件控制 |

### 2.4 音频（2026-11-19 全链路闭环）

| 器件 | 型号 / 地址 | 状态 | 说明 |
|---|---|---|---|
| DAC | **ES7148**（QFN-12，纯 I2S，无 I²C） | ✅ | 根因是 DTS 时钟 cell `0x56→0x59`（MCLK 上脚），用户耳听确认出声 |
| 麦阵 ADC | **ES7243 ×2** @ i2c1 `0x10` / `0x12` | ✅ | 同上根因，`arecord` 录到真实波形 |
| 喇叭功放 | 模拟输入 Class-D（无 I²C） | ✅ | `spk-con`(GPIO4_D1) + `amp-en`(GPIO4_A5) gpio-hog 常开 |
| 耳机功放 | **HT4832**（EN=pin13，低关断） | ✅ | GPIO4_D6=gpio158 由 `ht4832-en.service` 常驻拉高，左右声道实测正常 |
| 耳机检测 | GPIO4_D4=gpio156 | 🟡 | mainline 无 `rk_headset` 驱动，脚可手动接管 |
| 氛围灯 | **SN3732A ×3** @ i2c6 `0x50/0x52/0x53` | 🟡 | 寄存器语义无手册，原厂 APK JNI 控制，逆向中 |
| HDMI 音频 | `hdmi-sound` | ✅ | card1 |

> 详细根因链见 [`docs/音频架构-重新梳理-ES8316壳与Linux参考-20261119.md`](docs/音频架构-重新梳理-ES8316壳与Linux参考-20261119.md)。

### 2.5 摄像头 / 多媒体

| 器件 | 型号 / 地址 | 状态 | 说明 |
|---|---|---|---|
| 摄像头 sensor | Sony **IMX307** @ i2c4 `0x1a` | ✅ | 全链路设格式 + rebind 灌表后稳定 30 fps，60 帧 248,832,000 B，见 [`docs/camera/IMX307-EPIPE-根因-20261117.md`](docs/camera/IMX307-EPIPE-根因-20261117.md) |
| ISP | rkisp1 + CSI | ✅ | `/dev/video5-8`，需 isp:2 与 resizer 设 crop |
| GPU / VPU / 解码 / RGA / IEP | panfrost / hantro_vpu / rkvdec / rga / iep | ✅ | 全部驱动正常 |

### 2.6 网络 / 外设

| 器件 | 型号 | 状态 | 说明 |
|---|---|---|---|
| WiFi / BT | AP6255 (BCM4345C0) | ✅ | `brcmfmac` + `hci0` |
| 有线网 | 千兆 RGMII | ✅ | DTS 已配 |
| USB | xHCI | ✅ | 5 个 root hub |
| 云台电机驱动 | **AT8833**（杭州中科微，丝印 `AT8833 Y8C213C`） | 🔴 | 一建立输出电位差即过流、惰行即恢复；**驱动 v2.2 已交付**（定位语义 + OCP 状态机，`docs/云台-驱动定位语义v22与验收指南-20261122.md`），但**故障与驱动无关**——板级 AOUT 短路待万用表定位（§14.7 测量指南见同文档），见 `docs/云台-消费端-测试工具与会议程序-20261119.md` §12–§14 |

> **权威完整版**：[`docs/硬件清单-驱动状态-20261116.md`](docs/硬件清单-驱动状态-20261116.md)（含每项的实测证据、判伪记录和 GPIO 绑定表）。

---

## 3. 刷机方法

> **动手前必读**：[`docs/刷机指南.md`](docs/刷机指南.md)。刷机前先备份，出错时靠备份回退。

### 3.1 关键事实

- **板载微动按钮 = Reset**。它不是 MaskROM 键。
- **长按该微动按钮再上电** → 进入 **Loader 模式**（USB `0x2207:0x330c`，`rkdeveloptool ld` 显示 `Loader`）。
- 从 Loader 模式用命令进 **MaskROM 模式**：`rkdeveloptool rd 3`（`rd` 的参数 3 表示复位到 MaskROM；无参数 `rd` 会回到正常启动）。
- 这板带电池：只拔电源适配器不彻底，彻底断电要拔电池排线或长按电源键 15 s 放电。
- **Loader 与 MaskROM 的写盘坐标系不同**：MaskROM 下 `wl 0` 写物理 LBA 0；Loader 下 `wl 0` 实际写到物理 LBA 8192。**整盘 `wl 0` 前必须确认 `ld` 显示 `Maskrom`**，否则破坏原厂布局。

### 3.2 从原厂 Android 刷到 Armbian（标准流程）

```bash
# 0. 安装 rkdeveloptool（macOS / Linux 均需自行编译，见 docs/刷机指南.md）

# 1. 断电 → 长按板载微动按钮 → 插 OTG 数据线 → 上电 → 保持 2~3 s 后松开
#    此时 ld 显示 Loader
rkdeveloptool ld

# 2. Loader → MaskROM（关键一步）
rkdeveloptool rd 3
sleep 2
rkdeveloptool ld                 # 应显示 Maskrom

# 3. 下 DDR loader 到 SRAM（MaskROM → Loader，初始化 eMMC）
rkdeveloptool db firmware/loader/rk3399_loader_v1.30.130.bin

# 4. 写整盘 Armbian 镜像（此时已是 Loader，但 db 之后坐标仍是物理地址）
#    镜像来自 CI 产物，见 docs/适配过程.md
rkdeveloptool wl 0 armbian-rk3399-mid-24.img

# 5. 复位、拔 OTG、冷启动
rkdeveloptool rd
# 拔掉 USB 数据线，断电 10 s 再上电；TTL 串口 1500000 8N1 抓启动日志
```

### 3.3 loader.bin 源码索引

`rk3399_loader_v1.30.130.bin`（454,990 B）不是二进制黑盒，可用 Rockchip 官方 `rkbin` 仓库重建：

| 项 | 值 |
|---|---|
| 源码仓库 | `https://github.com/rockchip-linux/rkbin` |
| 打包配置 | `RKBOOT/RK3399MINIALL.ini` |
| 组件 | `bin/rk33/rk3399_ddr_800MHz_v1.30.bin`、`rk3399_usbplug_v1.30.bin`、`rk3399_miniloader_v1.30.bin` |
| 打包工具 | `./tools/boot_merger RKBOOT/RK3399MINIALL.ini` |
| 本仓库内的副本 | [`firmware/loader/rk3399_loader_v1.30.130.bin`](firmware/loader/rk3399_loader_v1.30.130.bin) |
| 重建 workflow | [`firmware/loader/build-rk3399-loader.yml`](firmware/loader/build-rk3399-loader.yml)（GitHub Actions 一键重建） |
| SHA256 | 见 [`firmware/loader/SHA256SUMS.txt`](firmware/loader/SHA256SUMS.txt) |

> loader 在 MaskROM 阶段只做两件事：初始化 DDR 和 USB，与板级外设无关。**同 SoC 的 loader 通用**。

### 3.4 回退到原厂

```bash
# 全盘原厂镜像不在本仓库（7.2 GB，超出 GitHub 单文件 100 MB 上限）
# 本地路径与校验和见 firmware/android-stock/README.md
rkdeveloptool wl 0 <原厂全盘镜像>
rkdeveloptool rd
```

---

## 4. 适配过程

从原厂 Android 到当前状态的完整过程，含每一阶段的问题、判伪、修复动作和验证结果：

**→ [`docs/适配过程.md`](docs/适配过程.md)**

快速入口：

| 阶段 | 内容 |
|---|---|
| 1 | 原厂系统备份与硬件扫描 |
| 2 | Armbian board config + DTS 首次适配 |
| 3 | 显示 / 触摸 / 电源 / 网络打通 |
| 4 | 音频 MCLK 根因闭环（一个 clock cell） |
| 5 | 摄像头 IMX307 + rkisp1 打通 |
| 6 | 云台 AT8833 逆向与驱动重写 |
| 7 | 当前状态与遗留问题 |

---

## 5. 仓库结构

```
.
├── README.md                       # 本文件
├── docs/
│   ├── 适配过程.md                  # 从 0 到当前的完整记录
│   ├── 刷机指南.md                  # 刷机命令与注意事项
│   ├── 支持作者.md                  # 打赏与支持方式
│   ├── 硬件清单-驱动状态-20261116.md # 权威硬件清单（证据链完整）
│   ├── 文档导航-从取证弯路到最终结论.md
│   ├── camera/                     # 摄像头专项文档
│   ├── 开发资料/                    # 芯片手册、硬件原始事实、逆向脚本
│   └── assets/                     # 图片资源
├── firmware/
│   ├── android-stock/              # 原厂 Android 分区备份（<100 MB 部分）
│   ├── loader/                     # RK3399 DDR loader + 重建 workflow
│   └── README.md                   # 固件清单与大文件说明
├── armbian/
│   ├── userpatches/config/boards/rk3399-mid.csc   # Armbian 板级配置
│   ├── userpatches/kernel/archive/rockchip64-6.18/dt/rk3399-mid.dts  # 自编主 DTS
│   └── userpatches/kernel/archive/rockchip64-6.18/*.patch
├── kernel-modules/
│   ├── es7243/                     # ES7243 麦阵 ADC 驱动
│   ├── hr8833/                     # AT8833 云台驱动（纯净版：仅 vendor ioctl，无诊断/状态机）
│   └── gpioprobe/                  # GPIO 调试工具
├── overlay/rk3399-mid-camera-regs.dts  # 摄像头寄存器覆盖
├── tools/                          # 构建、测试、诊断脚本
├── dist/                           # U-Boot 产物、DTB、测试脚本
└── .github/workflows/              # CI：build-armbian.yml / build-uboot.yml / build-modules.yml
```

---

## 6. 支持作者

如果这个项目帮你省了时间，可以考虑打赏。入口在 [`docs/支持作者.md`](docs/支持作者.md)。

---

## 7. 免责声明

本仓库为个人硬件折腾记录，非商业产品。刷机有变砖风险，**动手前必须备份全盘镜像**。所有命令在作者设备上实测通过，不保证在你的设备上行为一致。按本仓库操作造成的硬件损坏，作者不承担责任。
