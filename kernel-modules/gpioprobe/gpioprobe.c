// SPDX-License-Identifier: GPL-2.0-only
/*
 * gpioprobe.c - RK3399 GPIO 引脚电平快照（诊断用，不注册任何设备）
 *
 * GPIO_EXT_PORT 反映引脚的**真实电平**，与 IOMUX 复用到哪个外设无关。
 * 所以即使 GPIO3_D0..D7 已经被 i2s0 占用、GPIO4_A0 被复用成 I2S0_MCLK，
 * 也能读出它们当前是高还是低、是否在翻转 —— 用来判断：
 *   - SCLK/LRCK 有没有波形（SoC 是不是真的在主模式出时钟）
 *   - MCLK(GPIO4_A0) 有没有波形（12.288MHz 下随机采样必然 low/high 混合）
 *   - SDI0/SDI1 是不是恒高（= ES7243 SDOUT 高阻，根本没输出）
 *
 * 不取 clk：pinctrl 一直在操作这批寄存器，pclk 必然是开的；
 * 之前用户态 /dev/mem 直接 mmap 会 oops，是 mmap 路径的问题，内核 ioremap 没有。
 *
 * 用法：
 *   insmod gpioprobe.ko
 *   insmod gpioprobe.ko samples=50000
 */

#include <linux/module.h>
#include <linux/io.h>
#include <linux/delay.h>

#define GPIO3_BASE	0xFF7A0000UL
#define GPIO4_BASE	0xFF790000UL
#define GPIO_EXT_PORT	0x0050
#define NPINS3		8
#define FIRST_PIN3	24	/* gpio3_D0 */

static int samples = 200000;
module_param(samples, int, 0644);

static const char *name3[NPINS3] = {
	"SCLK", "LRCK_RX", "LRCK_TX", "SDI0",
	"SDI1", "SDI2", "SDI3", "SDO0",
};

static int __init gp_init(void)
{
	void __iomem *b3, *b4;
	unsigned int lo[NPINS3] = { 0 }, hi[NPINS3] = { 0 };
	unsigned int mclk_lo = 0, mclk_hi = 0;
	u32 v, v4;
	int i, p;

	b3 = ioremap(GPIO3_BASE, 0x100);
	b4 = ioremap(GPIO4_BASE, 0x100);
	if (!b3 || !b4) {
		pr_err("gpioprobe: ioremap failed\n");
		if (b3)
			iounmap(b3);
		if (b4)
			iounmap(b4);
		return -ENOMEM;
	}

	for (i = 0; i < samples; i++) {
		v = readl(b3 + GPIO_EXT_PORT);
		for (p = 0; p < NPINS3; p++) {
			if (v & (1 << (FIRST_PIN3 + p)))
				hi[p]++;
			else
				lo[p]++;
		}
		v4 = readl(b4 + GPIO_EXT_PORT);
		if (v4 & 1)		/* gpio4_A0 = I2S0_MCLK */
			mclk_hi++;
		else
			mclk_lo++;
	}

	for (p = 0; p < NPINS3; p++)
		pr_info("gpioprobe: gpio3_%d %-8s low=%u high=%u%s\n",
			FIRST_PIN3 + p, name3[p], lo[p], hi[p],
			(lo[p] && hi[p]) ? "  <== TOGGLING" : "");

	pr_info("gpioprobe: gpio4_0 MCLK     low=%u high=%u%s\n",
		mclk_lo, mclk_hi,
		(mclk_lo && mclk_hi) ? "  <== TOGGLING" : "");

	iounmap(b3);
	iounmap(b4);
	return 0;
}

static void __exit gp_exit(void)
{
}

module_init(gp_init);
module_exit(gp_exit);

MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("RK3399 GPIO level snapshot (diagnostic)");
