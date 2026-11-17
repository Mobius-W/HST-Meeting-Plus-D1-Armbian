// SPDX-License-Identifier: GPL-2.0-only
/*
 * gpioprobe.c - RK3399 GPIO 引脚电平快照（诊断用，不注册任何设备）
 *
 * 为什么需要它：
 *   板端 /dev/mem 直接 ioremap GPIO 会因 pclk 未使能而触发内核异常（实测
 *   导致整机 oops + 自动重启），所以必须先 clk_prepare_enable(pclk_gpio3)
 *   再访问 GPIO_EXT_PORT。
 *
 * 用途：
 *   GPIO_EXT_PORT 反映引脚的**真实电平**，与 IOMUX 复用到哪个外设无关。
 *   所以即使 GPIO3_D0..D7 已经被 i2s0 占用，也能读出 SCLK/LRCK/SDI0/SDI1
 *   当前是高还是低、是否在翻转 —— 用来判断 ES7243 的 SDOUT 到底有没有
 *   输出数据（恒高 = 高阻/没驱动）。
 *
 * 用法：
 *   insmod gpioprobe.ko            # 采样 200000 次，抖动的引脚会 low/high 都有
 *   insmod gpioprobe.ko samples=50000
 */

#include <linux/module.h>
#include <linux/io.h>
#include <linux/clk.h>
#include <linux/delay.h>

#define GPIO3_BASE	0xFF7A0000UL
#define GPIO_EXT_PORT	0x0050
#define NPINS		8
#define FIRST_PIN	24	/* gpio3_D0 */

static int samples = 200000;
module_param(samples, int, 0644);

static const char *pin_name[NPINS] = {
	"SCLK", "LRCK_RX", "LRCK_TX", "SDI0",
	"SDI1", "SDI2", "SDI3", "SDO0",
};

static int __init gp_init(void)
{
	void __iomem *base;
	struct clk *pclk;
	unsigned int lo[NPINS] = { 0 }, hi[NPINS] = { 0 };
	u32 v;
	int i, p, ret;

	pclk = clk_get_sys(NULL, "pclk_gpio3");
	if (IS_ERR(pclk)) {
		pr_err("gpioprobe: no pclk_gpio3 (%ld), refuse to touch GPIO\n",
		       PTR_ERR(pclk));
		return -ENODEV;
	}

	ret = clk_prepare_enable(pclk);
	if (ret) {
		pr_err("gpioprobe: pclk enable failed %d\n", ret);
		return ret;
	}

	base = ioremap(GPIO3_BASE, 0x100);
	if (!base) {
		pr_err("gpioprobe: ioremap failed\n");
		return -ENOMEM;
	}

	for (i = 0; i < samples; i++) {
		v = readl(base + GPIO_EXT_PORT);
		for (p = 0; p < NPINS; p++) {
			if (v & (1 << (FIRST_PIN + p)))
				hi[p]++;
			else
				lo[p]++;
		}
	}

	for (p = 0; p < NPINS; p++)
		pr_info("gpioprobe: gpio3_%d %-8s low=%u high=%u%s\n",
			FIRST_PIN + p, pin_name[p], lo[p], hi[p],
			(lo[p] && hi[p]) ? "  <== TOGGLING" : "");

	iounmap(base);
	/* 故意不关 pclk，避免下次 /dev/mem 又踩坑 */
	return 0;
}

static void __exit gp_exit(void)
{
}

module_init(gp_init);
module_exit(gp_exit);

MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("RK3399 GPIO3 level snapshot (diagnostic)");
