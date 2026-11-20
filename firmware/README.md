# 固件资产清单

本目录收录 HST Meeting Plus D1 适配过程中用到的固件与备份。

## 收录范围（GitHub 单文件上限 100 MB）

| 类别 | 路径 | 体积 | 是否入库 |
|---|---|---|---|
| 原厂小分区（boot/recovery/resource/trust/uboot/misc/baseparamer/kernel/metadata/frp/verity_mode） | [`android-stock/`](android-stock/) | 32 MB ~ 512 KB 每个 | ✅ 已入库 |
| 原厂分区表 / 参数 | [`android-stock/parameter.txt`](android-stock/parameter.txt)、[`android-stock/PARTITIONS-AUTHORITATIVE.txt`](android-stock/PARTITIONS-AUTHORITATIVE.txt) | < 3 KB | ✅ 已入库 |
| DDR loader（454,990 B）+ 源码索引 | [`loader/`](loader/) | 444 KB | ✅ 已入库 |
| 原厂 system.img | `stock/system.img` | 1,610,612,736 B（1.5 GiB） | ❌ 超上限，留本地 |
| 原厂 cache.img / backup.img / userdata.img | — | 128 MB / 112 MB / 5.3 GiB | ❌ 超上限，留本地 |
| 原厂全盘镜像 | `rescue/rk3399-mid-emmc-full-20261110.img` | 7,820,083,200 B（7.2 GiB） | ❌ 超上限，留本地 |
| Armbian 整盘镜像 | CI 产物 | ~1.7 GiB | ❌ 超上限，走 Actions artifact |

> 大文件获取方式：Armbian 镜像用仓库的 `.github/workflows/build-armbian.yml` 自己编译（约 69 分钟）；原厂大分区需从原机备份（方法见 [`docs/适配过程.md`](../docs/适配过程.md) 阶段 0）。

## 校验和

### 全盘原厂镜像（本地备份，SHA256）

```
3f9e81a4c9e3310007c3bc4188e49865811db03f2218c1611889fbfea514fa72  rk3399-mid-emmc-full-20261110.img
```

### 原厂 system.img（本地备份，SHA256）

```
efbd874036601715852bf00d4d68d305bceeeb079b7a214e8a0c44d3361398c7  system.img
```

### 原厂小分区（MD5，原始备份时的校验记录）

见 [`android-stock/SHA256SUMS`](android-stock/SHA256SUMS)（文件名沿袭备份时的命名，实为 MD5）。

### DDR loader（SHA256）

```
78e7d3ed43463fe1cc57296855c01c25c9d30e7e64e71913ac62760b61b0407f  rk3399_loader_v1.30.130.bin
```

## loader.bin 源码索引

`rk3399_loader_v1.30.130.bin`（454,990 B）是 Rockchip 官方 `rkbin` 仓库的产物，非二进制黑盒：

- 仓库：`https://github.com/rockchip-linux/rkbin`
- 配置：`RKBOOT/RK3399MINIALL.ini`
- 组件：`bin/rk33/rk3399_ddr_800MHz_v1.30.bin`、`rk3399_usbplug_v1.30.bin`、`rk3399_miniloader_v1.30.bin`
- 打包：`./tools/boot_merger RKBOOT/RK3399MINIALL.ini`
- 本仓库的构建 workflow：[`loader/build-rk3399-loader.yml`](loader/build-rk3399-loader.yml)（`workflow_dispatch` 触发，输出同款 bin）
- 配置副本：[`loader/RK3399MINIALL.ini`](loader/RK3399MINIALL.ini)

loader 只在 MaskROM 阶段初始化 DDR 与 USB，与板级外设无关，同 SoC 通用。

## 分区 LBA 坐标

见 [`android-stock/PARTITIONS-AUTHORITATIVE.txt`](android-stock/PARTITIONS-AUTHORITATIVE.txt)。刷机前必读 [`docs/刷机指南.md`](../docs/刷机指南.md) 的 MaskROM/Loader 坐标系警告。
