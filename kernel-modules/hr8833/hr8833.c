// SPDX-License-Identifier: GPL-2.0-only
/*
 * hr8833.c - 纯净版驱动（针对 AT8833，完全按 vendor 语义）
 *
 * 目标板：RK3399 视频会议一体机（视维 fsmeeting / rk3399-mid）
 *
 * ★ 芯片型号：AT8833（杭州中科微），丝印 AT8833 Y8C213C
 *
 * ★ v2.1 的问题（2026-11-19）：
 *   1. hrtimer 在 softirq 里 20 kHz 翻转 GPIO，与芯片内部 50 kHz 斩波冲突
 *   2. 唤醒只等 1–2 ms，余量不足（tWAKE 上限 1 ms）
 *   3. 没有 OCP 检测，无法诊断
 *   4. 启动前故障自愈 + 可观测（auto_reset）改变了观测条件
 *
 * ★ v2（纯净版）设计原则：
 *   1. 完全复刻 vendor ioctl 三个 cmd（0x18/0x19/0x1a），arg 被忽略
 *   2. **不切 nSLEEP**（vendor 从不碰 nSLEEP，只在 probe 初始化后不再管）
 *   3. 纯直驱满速，不搞软件 PWM
 *   4. 移除所有诊断（nFAULT 中断、irq_stat、fault_state 等）
 *   5. 移除所有状态机（autocoast、冷却期、锁存等）
 *   6. 简化到极致：只有基础 probe/remove + 三个 vendor ioctl
 *
 * ★ AT8833 关键规格（AT8833-S402-V1.4）：
 *   VM 2.7–15 V        —— 板上 12 V 合规
 *   IOCP 2.2–3 A, tDEG 1.5 µs, tOCP 1.9 ms
 *   nFAULT 开漏，仅 OCP / TSD 拉低
 *   tWAKE 0.2–1 ms     —— nSLEEP 拉高到 H 桥真正工作
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/gpio/consumer.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>

#define HR8833_IOC_MAGIC	'H'

/* 三个 vendor ioctl，完全复刻 vendor 语义（2026-11-19 反汇编） */
#define HR8833_VENDOR_IOC_ENABLE  _IOW(HR8833_IOC_MAGIC, 0x18, int) /* Ioenable = 停止/惰行 */
#define HR8833_VENDOR_IOC_FWD	  _IOW(HR8833_IOC_MAGIC, 0x19, int) /* Ioforward = 正转 */
#define HR8833_VENDOR_IOC_REV	  _IOW(HR8833_IOC_MAGIC, 0x1a, int) /* Ioreverse = 反转 */

struct hr8833 {
	struct device *dev;
	struct miscdevice miscdev;

	struct gpio_desc *ain1;
	struct gpio_desc *ain2;
	struct gpio_desc *sleep;
	struct gpio_desc *ocp;
};

/* ---------------- 底层引脚操作 ---------------- */

static void hr8833_pins_idle(struct hr8833 *h)
{
	/* 0x18: AIN1=0, AIN2=0（惰行/停止，名字误导，实为 stop） */
	gpiod_set_value(h->ain1, 0);
	gpiod_set_value(h->ain2, 0);
}

static void hr8833_pins_fwd(struct hr8833 *h)
{
	/* 0x19: AIN1=0, AIN2=1（正转，满速） */
	gpiod_set_value(h->ain1, 0);
	gpiod_set_value(h->ain2, 1);
}

static void hr8833_pins_rev(struct hr8833 *h)
{
	/* 0x1a: AIN1=1, AIN2=0（反转，满速） */
	gpiod_set_value(h->ain1, 1);
	gpiod_set_value(h->ain2, 0);
}

/* ---------------- 文件接口 ---------------- */

static int hr8833_open(struct inode *inode, struct file *file)
{
	struct miscdevice *misc = file->private_data;

	file->private_data = container_of(misc, struct hr8833, miscdev);
	return 0;
}

static long hr8833_ioctl(struct file *file, unsigned int cmd,
			 unsigned long arg)
{
	struct hr8833 *h = file->private_data;

	switch (cmd) {
	case HR8833_VENDOR_IOC_ENABLE:	/* 0x18 = 停止/惰行 */
		hr8833_pins_idle(h);
		return 0;

	case HR8833_VENDOR_IOC_FWD:	/* 0x19 = 正转 */
		hr8833_pins_fwd(h);
		return 0;

	case HR8833_VENDOR_IOC_REV:	/* 0x1a = 反转 */
		hr8833_pins_rev(h);
		return 0;

	default:
		return -ENOTTY;
	}
}

static const struct file_operations hr8833_fops = {
	.owner		= THIS_MODULE,
	.open		= hr8833_open,
	.unlocked_ioctl	= hr8833_ioctl,
};

/* ---------------- probe / remove ---------------- */

static int hr8833_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct hr8833 *h;
	int ret;

	h = devm_kzalloc(dev, sizeof(*h), GFP_KERNEL);
	if (!h)
		return -ENOMEM;

	h->dev = dev;

	/* 读取引脚定义（DTS 中为 ain1-gpio, ain2-gpio, sleep-gpio） */
	h->ain1 = devm_gpiod_get(dev, "ain1", GPIOD_OUT_LOW);
	if (IS_ERR(h->ain1))
		return dev_err_probe(dev, PTR_ERR(h->ain1), "no ain1-gpios\n");

	h->ain2 = devm_gpiod_get(dev, "ain2", GPIOD_OUT_LOW);
	if (IS_ERR(h->ain2))
		return dev_err_probe(dev, PTR_ERR(h->ain2), "no ain2-gpios\n");

	/* sleep-gpio: ACTIVE_LOW，1 = 物理高 = 唤醒 */
	h->sleep = devm_gpiod_get(dev, "sleep", GPIOD_OUT_HIGH);
	if (IS_ERR(h->sleep))
		return dev_err_probe(dev, PTR_ERR(h->sleep), "no sleep-gpios\n");

	/* ocp-det-gpio: 读取用于调试（纯净版不注册中断） */
	h->ocp = devm_gpiod_get_optional(dev, "ocp-det", GPIOD_IN);
	if (IS_ERR(h->ocp))
		return dev_err_probe(dev, PTR_ERR(h->ocp), "bad ocp-det-gpios\n");

	/* 上电初始化：nSLEEP 高（唤醒），AIN1/AIN2 低（惰行） */
	hr8833_pins_idle(h);
	gpiod_set_value(h->sleep, 1);

	dev_info(dev, "AT8833 pure driver ready (/dev/hr8833, vendor ioctl 0x18/19/1a)\n");

	return 0;
}

static int hr8833_remove(struct platform_device *pdev)
{
	struct hr8833 *h = platform_get_drvdata(pdev);

	/* 退出时彻底停机，nSLEEP 拉高（芯片休眠） */
	hr8833_pins_idle(h);
	gpiod_set_value(h->sleep, 1);

	return 0;
}

/* ---------------- 设备模型 ---------------- */

static struct platform_driver hr8833_driver = {
	.probe = hr8833_probe,
	.remove = hr8833_remove,
	.driver = {
		.name = "hr8833",
		.of_match_table = of_match_ptr(hr8833_of_match),
	},
};

static struct miscdevice hr8833_miscdev = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "hr8833",
	.fops = &hr8833_fops,
};

static int __init hr8833_init(void)
{
	int ret;

	ret = platform_driver_register(&hr8833_driver);
	if (ret)
		return ret;

	ret = misc_register(&hr8833_miscdev);
	if (ret) {
		platform_driver_unregister(&hr8833_driver);
		return ret;
	}

	return 0;
}

static void __exit hr8833_exit(void)
{
	misc_deregister(&hr8833_miscdev);
	platform_driver_unregister(&hr8833_driver);
}

module_init(hr8833_init);
module_exit(hr8833_exit);

MODULE_AUTHOR("HST Meeting Plus D1");
MODULE_DESCRIPTION("AT8833 pure driver: vendor ioctl 0x18/19/1a only, no diagnosis, no state machine");
MODULE_LICENSE("GPL-2.0-only");
MODULE_DEVICE_TABLE(of, hr8833_of_match);
