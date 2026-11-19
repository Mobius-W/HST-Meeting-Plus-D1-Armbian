// SPDX-License-Identifier: GPL-2.0-only
/*
 * hr8833.c - AT8833 / HR8833 双 H 桥单轴云台电机驱动（v2 诊断版）
 *
 * 目标板：RK3399 视频会议一体机（视维 fsmeeting / rk3399-mid）
 *
 * ★ 芯片型号更正（2026-11-19）：板上丝印为 AT8833（杭州中科微），
 *   与 HR8833 仅 pin-to-pin 兼容（同属 DRV8833 系），内部参数不同。
 *   compatible 沿用原厂 "heroic,hr8833"（vendor DTB 原值），驱动只做
 *   GPIO 级操作，两颗通用。
 *
 * AT8833 关键规格（AT8833-S402-V1.4）：
 *   VM 2.7–15 V        —— 板上 12 V 合规
 *   IOCP 2.2–3 A, tDEG 1.5 µs, tOCP 1.9 ms（过流后自动重试）
 *   TSD 160 ℃ 关断，需降 45 ℃ 才恢复（ls 锁存）
 *   nFAULT 开漏，仅 OCP / TSD 拉低（UVLO 不拉低）
 *   tWAKE 0.2–1 ms     —— nSLEEP 拉高到 H 桥真正工作
 *   控制表：00=滑行(ZZ)  01=反转(LH)  10=正转(HL)  11=刹车(LL)
 *
 * 硬件引脚（取自 vendor DTB /motor 节点，GPIO2_A2~A5）：
 *   AIN1      GPIO2_A2   控制 AOUT1
 *   AIN2      GPIO2_A3   控制 AOUT2
 *   nSLEEP    GPIO2_A4   ACTIVE_LOW（逻辑 1 = 休眠，逻辑 0 = 工作）
 *   nFAULT    GPIO2_A5   ACTIVE_LOW，开漏 + PULL_UP（逻辑 1 = 故障）
 *
 * ── v2 相对 v1 的改动 ────────────────────────────────────────────
 * 1) ★ 新增 nFAULT 中断统计（本驱动最重要的诊断能力）
 *    v1 只能靠用户态 12 µs 轮询，而 AT8833 的 OCP 重试窗口只有
 *    ~1.5 µs，弱上拉 RC 使上升沿几乎不可见，轮询必然读成"恒低"，
 *    从而无法区分「持续短路」和「1.9 ms hiccup 重试」。
 *    v2 在内核里注册双边沿中断，精确统计 fall/rise 次数与间隔，
 *    直接判定是 hiccup OCP 还是锁存式故障。
 *
 * 2) ★ 去掉 hrtimer 软件 PWM（20 kHz / softirq 上下文翻转 GPIO）
 *    - 40k 次/秒回调，与芯片内部 50 kHz 电流斩波相互干扰；
 *    - gpiod_set_value() 在软中断里调用本身不是好实践；
 *    - 原厂 Android 也是纯 GPIO 直驱，云台只需要「方向 + 定时」。
 *    改为直驱满速，调速交由芯片内部电流环（xISEN）。speed 参数
 *    保留但其绝对值不再调制占空比，仅决定方向。
 *
 * 3) ★ nSLEEP 时序收紧
 *    唤醒后等待 tWAKE 上限的 2 倍（2 ms）再给方向；停机时先把两个
 *    方向脚拉低（coast），再拉低 nSLEEP，避免带电切换。
 *
 * 4) ★ 启动前故障自愈 + 可观测
 *    若启动瞬间 nFAULT 已是低，先切一次 nSLEEP 复位并重试；仍为低
 *    则判定持续故障、拒绝输出并返回 -EIO。sysfs 记录复位次数。
 *
 * 用户态接口：
 *   /dev/hr8833  (misc 0666)
 *     HR8833_IOC_RUN   {s32 speed; u32 ms;}   speed 符号=方向，ms>0 定时停
 *     HR8833_IOC_STOP / _WAKE / _SLEEP / _GET_OCP
 *     原厂兼容 magic 'm'：0x18 停, 0x19 正转, 0x1a 反转
 *   sysfs
 *     speed       (rw) 非 0 = 按符号方向直驱
 *     sleep_state (rw) 1 = 休眠
 *     ocp         (ro) 当前 nFAULT 逻辑值（1 = 故障）
 *     irq_stat    (ro) fall/rise 计数与 fall 间隔统计（诊断核心）
 *     fault_reset (wo) 写 1 触发一次 nSLEEP 复位
 *     clear_stat  (wo) 写 1 清零统计
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/gpio/consumer.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/ktime.h>
#include <linux/workqueue.h>
#include <linux/ioctl.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/err.h>
#include <linux/of.h>

/* nSLEEP 拉高到 H 桥可用：手册 tWAKE 0.2–1 ms，取 2 倍余量 */
#define HR8833_WAKE_MS		2

/* 故障复位后再次检查前的等待（等 nFAULT 上拉恢复） */
#define HR8833_FAULT_SETTLE_US	300

struct hr8833_cmd {
	__s32 speed;	/* 负 = 反转，正 = 正转，0 = 停止 */
	__u32 ms;	/* >0：运行 ms 毫秒后自动停机；0 = 一直转 */
};

#define HR8833_IOC_MAGIC	'H'
#define HR8833_IOC_RUN		_IOW(HR8833_IOC_MAGIC, 1, struct hr8833_cmd)
#define HR8833_IOC_STOP		_IO(HR8833_IOC_MAGIC, 2)
#define HR8833_IOC_WAKE		_IO(HR8833_IOC_MAGIC, 3)
#define HR8833_IOC_SLEEP	_IO(HR8833_IOC_MAGIC, 4)
#define HR8833_IOC_GET_OCP	_IOR(HR8833_IOC_MAGIC, 5, int)

/*
 * 原厂 Android ioctl 兼容层（2026-11-16 由 vendor 内核反汇编确认）。
 * fsmeeting 的 libJniioctl.so 用 magic='m' 控制 /dev/hr8833，只读 cmd、
 * 完全忽略 arg，三个分支是纯 GPIO 写：
 *   0x18 Ioenable  -> AIN1=0, AIN2=0  停止/惰行（名字误导，实为 STOP）
 *   0x19 Ioforward -> AIN1=0, AIN2=1  正转
 *   0x1a Ioreverse -> AIN1=1, AIN2=0  反转
 * App 侧 turnByAngle() 按 |angle| 毫秒延时后再发 0x18 停机。
 * 本层严格复刻该语义（不读 arg、不切 nSLEEP）。
 */
#define HR8833_VENDOR_MAGIC	'm'
#define HR8833_VENDOR_IOC_ENABLE  _IOW(HR8833_VENDOR_MAGIC, 0x18, int)
#define HR8833_VENDOR_IOC_FWD	  _IOW(HR8833_VENDOR_MAGIC, 0x19, int)
#define HR8833_VENDOR_IOC_REV	  _IOW(HR8833_VENDOR_MAGIC, 0x1a, int)

struct hr8833 {
	struct device *dev;
	struct miscdevice miscdev;

	struct gpio_desc *ain1;
	struct gpio_desc *ain2;
	struct gpio_desc *sleep;
	struct gpio_desc *ocp;

	int ocp_irq;

	struct mutex lock;	/* 保护状态机（可睡眠上下文） */
	spinlock_t slock;	/* 保护中断可见的统计字段 */

	int speed;
	bool running;
	bool sleep_state;

	struct delayed_work stop_work;

	/* ---- nFAULT 中断统计 ---- */
	u64 irq_fall;
	u64 irq_rise;
	u64 last_fall_ns;
	u64 gap_min_ns;
	u64 gap_max_ns;
	u64 gap_sum_ns;
	u64 gap_cnt;
	u32 fault_resets;	/* nSLEEP 复位次数 */
};

/* ---------------- 底层引脚操作（调用者持 lock 或已知无竞态） ---------------- */

static void hr8833_pins_idle(struct hr8833 *h)
{
	gpiod_set_value(h->ain1, 0);
	gpiod_set_value(h->ain2, 0);
}

/*
 * 唤醒 nSLEEP 并等待电荷泵稳定。
 * sleep_state == false 表示已唤醒，直接返回。
 */
static void hr8833_wake(struct hr8833 *h)
{
	if (!h->sleep_state)
		return;
	gpiod_set_value(h->sleep, 0);	/* ACTIVE_LOW：0 = 物理高 = 工作 */
	h->sleep_state = false;
	msleep(HR8833_WAKE_MS);
}

static void hr8833_sleep(struct hr8833 *h)
{
	hr8833_pins_idle(h);
	if (h->sleep_state)
		return;
	/*
	 * 先让方向脚保持低一段时间再拉低 nSLEEP，
	 * 避免在 H 桥仍导通时切断栅极驱动。
	 */
	udelay(5);
	gpiod_set_value(h->sleep, 1);
	h->sleep_state = true;
}

/*
 * 故障自愈：切一次 nSLEEP 让芯片内部逻辑复位。
 * AT8833 手册称 OCP 会以 tOCP=1.9 ms 自动重试，但实测 nFAULT 拉低后
 * 长时间不释放，因此这里显式复位一次以区分「锁存」与「持续故障」。
 *
 * 返回：0 = 复位后 nFAULT 已恢复高；-EIO = 仍为低（持续故障）
 */
static int hr8833_fault_reset(struct hr8833 *h)
{
	dev_warn(h->dev, "nFAULT asserted, cycling nSLEEP\n");

	hr8833_sleep(h);
	udelay(200);
	hr8833_wake(h);
	usleep_range(HR8833_FAULT_SETTLE_US, HR8833_FAULT_SETTLE_US * 2);
	h->fault_resets++;

	if (gpiod_get_value(h->ocp) > 0) {
		dev_err(h->dev, "nFAULT still low after reset (persistent fault)\n");
		return -EIO;
	}
	dev_info(h->dev, "nFAULT cleared after reset\n");
	return 0;
}

/* ---------------- 状态机 ---------------- */

/* 调用者必须持有 h->lock */
static void __hr8833_stop(struct hr8833 *h)
{
	h->running = false;
	h->speed = 0;
	cancel_delayed_work(&h->stop_work);
	hr8833_sleep(h);
}

/* 调用者必须持有 h->lock。返回 0 或 -EIO */
static int __hr8833_start(struct hr8833 *h, int speed, unsigned int ms)
{
	if (speed == 0) {
		__hr8833_stop(h);
		return 0;
	}

	hr8833_wake(h);

	/* 启动前若已处于故障态，先尝试复位 */
	if (gpiod_get_value(h->ocp) > 0) {
		int ret = hr8833_fault_reset(h);

		if (ret)
			return ret;	/* 持续故障：不输出，避免反复大电流 */
	}

	if (speed > 0) {
		gpiod_set_value(h->ain1, 1);
		gpiod_set_value(h->ain2, 0);
	} else {
		gpiod_set_value(h->ain1, 0);
		gpiod_set_value(h->ain2, 1);
	}

	h->speed = speed;
	h->running = true;

	cancel_delayed_work(&h->stop_work);
	if (ms)
		schedule_delayed_work(&h->stop_work, msecs_to_jiffies(ms));

	dev_dbg(h->dev, "start speed=%d ms=%u sleep=%d\n",
		speed, ms, h->sleep_state);
	return 0;
}

static void hr8833_stop_work(struct work_struct *work)
{
	struct hr8833 *h = container_of(to_delayed_work(work),
					struct hr8833, stop_work);

	mutex_lock(&h->lock);
	if (h->running) {
		dev_dbg(h->dev, "auto stop\n");
		__hr8833_stop(h);
	}
	mutex_unlock(&h->lock);
}

/* ---------------- nFAULT 中断：诊断核心 ---------------- */

/*
 * 在 hardirq 上下文只做计数，绝不睡眠、不打印。
 * 通过读当前电平判断是上升沿还是下降沿（因为注册了双边沿）。
 */
static irqreturn_t hr8833_ocp_isr(int irq, void *data)
{
	struct hr8833 *h = data;
	unsigned long flags;
	u64 now = ktime_get_ns();
	int val;

	val = gpiod_get_value(h->ocp) > 0 ? 1 : 0;

	spin_lock_irqsave(&h->slock, flags);
	if (val) {
		h->irq_rise++;
	} else {
		h->irq_fall++;
		if (h->last_fall_ns) {
			u64 gap = now - h->last_fall_ns;

			if (!h->gap_min_ns || gap < h->gap_min_ns)
				h->gap_min_ns = gap;
			if (gap > h->gap_max_ns)
				h->gap_max_ns = gap;
			h->gap_sum_ns += gap;
			h->gap_cnt++;
		}
		h->last_fall_ns = now;
	}
	spin_unlock_irqrestore(&h->slock, flags);

	return IRQ_HANDLED;
}

/* ---------------- 文件接口 ---------------- */

static int hr8833_open(struct inode *inode, struct file *file)
{
	struct miscdevice *misc = file->private_data;

	file->private_data = container_of(misc, struct hr8833, miscdev);
	return 0;
}

/*
 * 原厂兼容：纯 GPIO 直驱（复刻 vendor hr8833_ioctl）。
 * 与 v1 的区别：不再取消 hrtimer（已移除），但仍走完整 waking 时序。
 */
static int __hr8833_vendor_gpio(struct hr8833 *h, int ain1, int ain2)
{
	h->running = false;
	h->speed = 0;
	cancel_delayed_work(&h->stop_work);

	if (ain1 == 0 && ain2 == 0) {
		/* 0x18：stop → 惰行后休眠 */
		hr8833_sleep(h);
		return 0;
	}

	hr8833_wake(h);

	if (gpiod_get_value(h->ocp) > 0) {
		int ret = hr8833_fault_reset(h);

		if (ret)
			return ret;
	}

	/* 原厂极性：forward = AIN2 高，reverse = AIN1 高 */
	gpiod_set_value(h->ain1, ain1);
	gpiod_set_value(h->ain2, ain2);
	return 0;
}

static long hr8833_ioctl(struct file *file, unsigned int cmd,
			 unsigned long arg)
{
	struct hr8833 *h = file->private_data;
	struct hr8833_cmd c;
	int ocp;
	long ret = 0;

	mutex_lock(&h->lock);
	switch (cmd) {
	case HR8833_IOC_RUN:
		if (copy_from_user(&c, (void __user *)arg, sizeof(c))) {
			ret = -EFAULT;
			break;
		}
		ret = __hr8833_start(h, c.speed, c.ms);
		break;
	case HR8833_IOC_STOP:
		__hr8833_stop(h);
		break;
	case HR8833_IOC_WAKE:
		hr8833_wake(h);
		break;
	case HR8833_IOC_SLEEP:
		__hr8833_stop(h);
		break;
	case HR8833_IOC_GET_OCP:
		ocp = gpiod_get_value(h->ocp) > 0 ? 1 : 0;
		if (put_user(ocp, (int __user *)arg))
			ret = -EFAULT;
		break;
	case HR8833_VENDOR_IOC_ENABLE:	/* 0x18 停 */
		ret = __hr8833_vendor_gpio(h, 0, 0);
		break;
	case HR8833_VENDOR_IOC_FWD:	/* 0x19 正转 */
		ret = __hr8833_vendor_gpio(h, 0, 1);
		break;
	case HR8833_VENDOR_IOC_REV:	/* 0x1a 反转 */
		ret = __hr8833_vendor_gpio(h, 1, 0);
		break;
	default:
		ret = -ENOTTY;
	}
	mutex_unlock(&h->lock);

	return ret;
}

static const struct file_operations hr8833_fops = {
	.owner		= THIS_MODULE,
	.open		= hr8833_open,
	.unlocked_ioctl	= hr8833_ioctl,
};

/* ---------------- sysfs ---------------- */

static ssize_t speed_show(struct device *dev, struct device_attribute *attr,
			  char *buf)
{
	struct hr8833 *h = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%d\n", h->speed);
}

static ssize_t speed_store(struct device *dev, struct device_attribute *attr,
			   const char *buf, size_t count)
{
	struct hr8833 *h = dev_get_drvdata(dev);
	int val, ret;

	ret = kstrtoint(buf, 0, &val);
	if (ret)
		return ret;

	mutex_lock(&h->lock);
	ret = __hr8833_start(h, val, 0);
	mutex_unlock(&h->lock);

	return ret ? ret : count;
}
static DEVICE_ATTR_RW(speed);

static ssize_t sleep_state_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	struct hr8833 *h = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%d\n", h->sleep_state ? 1 : 0);
}

static ssize_t sleep_state_store(struct device *dev,
				 struct device_attribute *attr,
				 const char *buf, size_t count)
{
	struct hr8833 *h = dev_get_drvdata(dev);
	int val, ret;

	ret = kstrtoint(buf, 0, &val);
	if (ret)
		return ret;

	mutex_lock(&h->lock);
	if (val)
		__hr8833_stop(h);
	else
		hr8833_wake(h);
	mutex_unlock(&h->lock);

	return count;
}
static DEVICE_ATTR_RW(sleep_state);

static ssize_t ocp_show(struct device *dev, struct device_attribute *attr,
			char *buf)
{
	struct hr8833 *h = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%d\n", gpiod_get_value(h->ocp) > 0 ? 1 : 0);
}
static DEVICE_ATTR_RO(ocp);

/*
 * irq_stat —— 诊断核心输出。
 *   fall / rise : 自上次清零以来的边沿计数
 *   gap_*       : 相邻两次「下降沿」的间隔（即故障重复周期）
 *
 * 判读方法：
 *   fall≈157, rise≈156, gap≈1.9ms 400ms  ⇒ 典型 hiccup OCP（真过流且
 *                                            故障持续，芯片在反复重试）
 *   fall=1,   rise=0                     ⇒ nFAULT 拉低后锁存未释放
 *   fall=0,   rise=0                     ⇒ 完全没有故障（硬件正常）
 */
static ssize_t irq_stat_show(struct device *dev, struct device_attribute *attr,
			     char *buf)
{
	struct hr8833 *h = dev_get_drvdata(dev);
	unsigned long flags;
	u64 fall, rise, gmin, gmax, gsum, gcnt;
	u32 resets;

	spin_lock_irqsave(&h->slock, flags);
	fall = h->irq_fall;
	rise = h->irq_rise;
	gmin = h->gap_min_ns;
	gmax = h->gap_max_ns;
	gsum = h->gap_sum_ns;
	gcnt = h->gap_cnt;
	resets = h->fault_resets;
	spin_unlock_irqrestore(&h->slock, flags);

	return sysfs_emit(buf,
			  "fall=%llu rise=%llu irq=%d resets=%u\n"
			  "gap_min_us=%llu gap_max_us=%llu gap_avg_us=%llu gaps=%llu\n",
			  fall, rise, h->ocp_irq, resets,
			  gmin / 1000, gmax / 1000,
			  gcnt ? (gsum / gcnt) / 1000 : 0, gcnt);
}
static DEVICE_ATTR_RO(irq_stat);

static ssize_t fault_reset_store(struct device *dev,
				 struct device_attribute *attr,
				 const char *buf, size_t count)
{
	struct hr8833 *h = dev_get_drvdata(dev);
	int val, ret;

	ret = kstrtoint(buf, 0, &val);
	if (ret)
		return ret;
	if (!val)
		return count;

	mutex_lock(&h->lock);
	ret = hr8833_fault_reset(h);
	mutex_unlock(&h->lock);

	return ret ? ret : count;
}
static DEVICE_ATTR_WO(fault_reset);

static ssize_t clear_stat_store(struct device *dev,
				struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct hr8833 *h = dev_get_drvdata(dev);
	unsigned long flags;

	spin_lock_irqsave(&h->slock, flags);
	h->irq_fall = 0;
	h->irq_rise = 0;
	h->last_fall_ns = 0;
	h->gap_min_ns = 0;
	h->gap_max_ns = 0;
	h->gap_sum_ns = 0;
	h->gap_cnt = 0;
	spin_unlock_irqrestore(&h->slock, flags);

	return count;
}
static DEVICE_ATTR_WO(clear_stat);

static struct attribute *hr8833_attrs[] = {
	&dev_attr_speed.attr,
	&dev_attr_sleep_state.attr,
	&dev_attr_ocp.attr,
	&dev_attr_irq_stat.attr,
	&dev_attr_fault_reset.attr,
	&dev_attr_clear_stat.attr,
	NULL,
};

static const struct attribute_group hr8833_group = {
	.attrs = hr8833_attrs,
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
	mutex_init(&h->lock);
	spin_lock_init(&h->slock);
	h->sleep_state = true;

	h->ain1 = devm_gpiod_get(dev, "ain1", GPIOD_OUT_LOW);
	if (IS_ERR(h->ain1))
		return dev_err_probe(dev, PTR_ERR(h->ain1), "no ain1-gpios\n");

	h->ain2 = devm_gpiod_get(dev, "ain2", GPIOD_OUT_LOW);
	if (IS_ERR(h->ain2))
		return dev_err_probe(dev, PTR_ERR(h->ain2), "no ain2-gpios\n");

	h->sleep = devm_gpiod_get(dev, "sleep", GPIOD_OUT_HIGH);
	if (IS_ERR(h->sleep))
		return dev_err_probe(dev, PTR_ERR(h->sleep), "no sleep-gpios\n");

	h->ocp = devm_gpiod_get_optional(dev, "ocp-det", GPIOD_IN);
	if (IS_ERR(h->ocp))
		return dev_err_probe(dev, PTR_ERR(h->ocp), "bad ocp-det-gpios\n");

	/* 上电先保持休眠，方向脚低 */
	hr8833_pins_idle(h);
	gpiod_set_value(h->sleep, 1);
	h->sleep_state = true;

	INIT_DELAYED_WORK(&h->stop_work, hr8833_stop_work);

	/* ---- nFAULT 中断注册（诊断核心） ---- */
	if (h->ocp) {
		h->ocp_irq = gpiod_to_irq(h->ocp);
		if (h->ocp_irq > 0) {
			ret = devm_request_threaded_irq(
				dev, h->ocp_irq, hr8833_ocp_isr, NULL,
				IRQF_TRIGGER_FALLING | IRQF_TRIGGER_RISING |
					IRQF_SHARED,
				"hr8833-nfault", h);
			if (ret) {
				dev_warn(dev, "nFAULT irq %d failed: %d (统计不可用)\n",
					 h->ocp_irq, ret);
				h->ocp_irq = 0;
			} else {
				dev_info(dev, "nFAULT irq=%d, fall=%llu rise=%llu\n",
					 h->ocp_irq, h->irq_fall, h->irq_rise);
			}
		} else {
			dev_warn(dev, "no irq for nFAULT (gpiod_to_irq=%d)\n",
				 h->ocp_irq);
			h->ocp_irq = 0;
		}
	}

	h->miscdev.minor = MISC_DYNAMIC_MINOR;
	h->miscdev.name = "hr8833";
	h->miscdev.fops = &hr8833_fops;
	h->miscdev.parent = dev;
	h->miscdev.mode = 0666;

	platform_set_drvdata(pdev, h);

	ret = misc_register(&h->miscdev);
	if (ret) {
		dev_err(dev, "misc_register failed: %d\n", ret);
		return ret;
	}

	ret = devm_device_add_group(dev, &hr8833_group);
	if (ret) {
		dev_err(dev, "sysfs group failed: %d\n", ret);
		misc_deregister(&h->miscdev);
		return ret;
	}

	dev_info(dev, "AT8833 gimbal ready (/dev/hr8833, ocp=%d, irq=%d)\n",
		 gpiod_get_value(h->ocp) > 0 ? 1 : 0, h->ocp_irq);
	return 0;
}

static void hr8833_remove(struct platform_device *pdev)
{
	struct hr8833 *h = platform_get_drvdata(pdev);

	mutex_lock(&h->lock);
	__hr8833_stop(h);
	mutex_unlock(&h->lock);

	cancel_delayed_work_sync(&h->stop_work);
	misc_deregister(&h->miscdev);
}

static const struct of_device_id hr8833_of_match[] = {
	{ .compatible = "heroic,hr8833" },
	{ }
};
MODULE_DEVICE_TABLE(of, hr8833_of_match);

static struct platform_driver hr8833_driver = {
	.probe	= hr8833_probe,
	.remove	= hr8833_remove,
	.driver	= {
		.name		= "hr8833",
		.of_match_table	= hr8833_of_match,
	},
};
module_platform_driver(hr8833_driver);

MODULE_DESCRIPTION("AT8833/HR8833 single-axis gimbal motor driver (v2 diag)");
MODULE_AUTHOR("rk3399-mid bring-up");
MODULE_LICENSE("GPL");
