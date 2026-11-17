// SPDX-License-Identifier: GPL-2.0-only
/*
 * es7243.c - rk3399-mid 音频复合 codec 驱动
 *
 *   播放：ES7148（无寄存器纯 DAC）—— dummy 通路，只为让声卡有 playback 方向
 *   采集：2 x ES7243 麦阵 ADC（i2c1 0x10 / 0x12，级联 4 通道）—— 本驱动真正管的部分
 *
 * 为什么做成「一个复合 codec」而不是「标准 es7243 ASoC codec + 独立声卡」：
 *   原厂 Android 侧的结构就是这样——vendor es8316 codec 驱动统管播放(ES7148)
 *   与采集(ES7243 x2)，4 麦数据寄生在 es8316 声卡的 capture 通路上，DTS 里两颗
 *   ES7243 只是裸 i2c client，没有 #sound-dai-cells、不在任何 sound card 里，
 *   i2s1 是 disabled（见 docs 里的 4 麦链路取证报告）。
 *   mainline 的 simple-audio-card 一个 dai_link 只能挂一个 codec DAI，所以要让
 *   播放与采集共用 i2s0，就必须由一个 codec DAI 同时提供 playback 与 capture。
 *   ⇒ 本驱动 = mainline 版的「es8316」：playback 直通，capture 4ch 管两颗 ADC。
 *
 * 寄存器序列来源（不是照抄 datasheet，而是反汇编原厂 kernel.img 得来）：
 *   vendor 驱动 es7243_init / es7243_start / es7243_standby 的写入表，
 *   见 docs 与 /tmp/hw-hunt/es7243_vendor_analysis.md：
 *     init    : 0x00 = 0x01
 *     start   : 11 对（CLOCK MANAGER 0x01..0x09），唯一级联差异 reg 0x08
 *               0x10 芯片 = 0x41，0x12 芯片 = 0x21
 *     standby : 0x06=0x05, 0x05=0x1b, 0x06=0x5c, 0x09=0x9f
 *
 * ⚠ 板上芯片的 I2C 只有低 4 位参与寻址（实测：写 0x28 后读 0x08 得到同值），
 *   CHIP_ID 0xFD/0xFE 读到的 0x60/0x40 其实只是 0x0D/0x0E 的镜像，不能当型号判据。
 *   因此本驱动不做任何 CHIP_ID 校验（原厂驱动也不做）。
 *
 * 运行时可调（module param，方便在板子上不改代码试参数）：
 *   power_on_probe=1  probe 时就直接 init+start（不依赖 ALSA，纯验证 i2c 时序）
 *   tdm_first=<v>     start 之后给 0x10 芯片补写 reg 0x0C = v（默认 -1 = 不写）
 *   tdm_sync=<v>      给 0x12 芯片补写 reg 0x0C = v（默认 -1 = 不写）
 *   dump_regs=1       start/standby 后把 0x00..0x0F 打进 dmesg
 *
 * Date: 2026-11-16
 */

#include <linux/module.h>
#include <linux/i2c.h>
#include <linux/of.h>
#include <linux/clk.h>
#include <linux/slab.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <sound/soc.h>
#include <sound/pcm_params.h>

#define MID_ADC_MAX	2

/* vendor es7243_start 表：11 对，顺序不能改（原厂就是这么写的） */
static const u8 es7243_start_seq[][2] = {
	{ 0x06, 0x18 },
	{ 0x01, 0x0c },
	{ 0x02, 0x10 },
	{ 0x03, 0x04 },
	{ 0x04, 0x02 },
	{ 0x05, 0x1a },
	{ 0x08, 0x41 },	/* ★ 级联差异点：0x12 芯片改成 0x21，见下 */
	{ 0x07, 0x80 },
	{ 0x09, 0x00 },
	{ 0x06, 0x00 },
	{ 0x05, 0x13 },
};

/*
 * ESP-ADF（ESP32 板实测可用）的 ES7243 从机模式最小序列：
 *   0x00=0x01, 0x06=0x00, 0x05=0x1b, 0x01=0x0c, 0x08=gain, 0x05=0x13
 * 与 vendor 相比省掉了 0x02/0x03/0x04/0x07/0x09 这几项时钟分频。
 * seq=esp 时用它做对照实验（见 ESPHome es7243.cpp / ESP-ADF es7243.c）。
 */
static const u8 es7243_start_seq_min[][2] = {
	{ 0x06, 0x00 },
	{ 0x05, 0x1b },
	{ 0x01, 0x0c },
	{ 0x08, 0x41 },	/* 增益：0x12 芯片仍改 0x21 */
	{ 0x05, 0x13 },
};

/* vendor es7243_set_standby 表：4 对 */
static const u8 es7243_standby_seq[][2] = {
	{ 0x06, 0x05 },
	{ 0x05, 0x1b },
	{ 0x06, 0x5c },
	{ 0x09, 0x9f },
};

/* 第二颗芯片（i2c 0x12）在 start 表第 6 项（i=6, reg 0x08）要写 0x21 */
#define ES7243_SYNC_ADDR	0x12
#define ES7243_START_CASCADE_IDX	6

struct mid_adc {
	struct i2c_adapter *adap;
	u16 addr;
};

struct mid_audio {
	struct device *dev;
	struct mid_adc adc[MID_ADC_MAX];
	int num_adc;
	unsigned int mclk;
	struct clk *mclk_clk;
	bool adc_on;
};

static int tdm_first = -1;
module_param(tdm_first, int, 0644);
MODULE_PARM_DESC(tdm_first, "extra reg 0x0C value for chip 0x10 (-1 = don't write)");

static int tdm_sync = -1;
module_param(tdm_sync, int, 0644);
MODULE_PARM_DESC(tdm_sync, "extra reg 0x0C value for chip 0x12 (-1 = don't write)");

static bool power_on_probe;
module_param(power_on_probe, bool, 0644);
MODULE_PARM_DESC(power_on_probe, "init+start the ADCs at probe time");

static bool dump_regs = true;
module_param(dump_regs, bool, 0644);
MODULE_PARM_DESC(dump_regs, "dump regs 0x00..0x0F to dmesg after start/standby");

/*
 * 本板只有一条 LRCK/SCLK 网络：ES7148 与两颗 ES7243 都吃 SoC 的
 * LRCK_TX/SCLK_TX 这一对时钟脚（板级只有一条 I2S 时钟线，ADC 无从机时钟源）。
 * 而 rockchip_i2s 默认是 TRCM_TXRX —— RX 用自己的 LRCK_RX/SCLK_RX 引脚，
 * 那条线上没人驱动 ⇒ 采集永远读到 0xFFFF（FIFO 没被时钟推）。
 *
 * 修法：让 dai_link->symmetric_rate = 1，rockchip_i2s 就会切到 TRCM_TXONLY
 * （RX 复用 TX 的时钟脚）。simple-audio-card 没有对应的 DT 属性，所以先在这里
 * 直接改 rtd->dai_link。等验证过后再换成自写 machine driver 的正规做法。
 */
static int seq_variant;
module_param(seq_variant, int, 0644);
MODULE_PARM_DESC(seq_variant, "0 = vendor 11-write sequence, 1 = ESP-ADF minimal 6-write");

static bool auto_bclk_ratio = true;
module_param(auto_bclk_ratio, bool, 0644);
MODULE_PARM_DESC(auto_bclk_ratio, "set cpu dai bclk_ratio = 32 * channels");

static bool trcm_txonly = true;
module_param(trcm_txonly, bool, 0644);
MODULE_PARM_DESC(trcm_txonly, "force dai_link->symmetric_rate (TRCM_TXONLY)");

/* ------------------------------------------------------------------ */
/* I2C 访问：与 vendor 完全一致 —— 一次 i2c_transfer 发 {reg, val} 两字节  */
/* ------------------------------------------------------------------ */

static int adc_write(struct mid_audio *priv, int chip, u8 reg, u8 val)
{
	u8 buf[2] = { reg, val };
	struct i2c_msg msg = {
		.addr	= priv->adc[chip].addr,
		.flags	= 0,
		.len	= 2,
		.buf	= buf,
	};
	int ret, tries;

	/*
	 * ES7243 在没看到 MCLK 之前不应答 I2C（ESPHome 的 es7243 驱动里明确写了
	 * "The chip ignores I2C until it has seen MCLK"）。MCLK 由本驱动在 probe
	 * 时打开并常开，但如果时钟刚起或芯片刚从休眠醒来，第一次写仍可能 NAK，
	 * 所以这里带重试。
	 */
	for (tries = 0; tries < 5; tries++) {
		ret = i2c_transfer(priv->adc[chip].adap, &msg, 1);
		if (ret == 1)
			return 0;
		usleep_range(2000, 3000);
	}

	dev_err(priv->dev, "i2c write %02x:%02x=%02x failed (%d)\n",
		priv->adc[chip].addr, reg, val, ret);
	return ret < 0 ? ret : -EIO;
}

static int adc_read(struct mid_audio *priv, int chip, u8 reg, u8 *val)
{
	struct i2c_msg msg[2] = {
		{
			.addr	= priv->adc[chip].addr,
			.flags	= 0,
			.len	= 1,
			.buf	= &reg,
		}, {
			.addr	= priv->adc[chip].addr,
			.flags	= I2C_M_RD,
			.len	= 1,
			.buf	= val,
		},
	};
	int ret = i2c_transfer(priv->adc[chip].adap, msg, 2);

	return ret == 2 ? 0 : (ret < 0 ? ret : -EIO);
}

static void adc_dump(struct mid_audio *priv, const char *tag)
{
	u8 v[16];
	int c, i;

	if (!dump_regs)
		return;

	for (c = 0; c < priv->num_adc; c++) {
		for (i = 0; i < 16; i++) {
			if (adc_read(priv, c, i, &v[i]))
				v[i] = 0xee;
		}
		dev_info(priv->dev,
			 "%s adc[%d]@%02x: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
			 tag, c, priv->adc[c].addr,
			 v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7],
			 v[8], v[9], v[10], v[11], v[12], v[13], v[14], v[15]);
	}
}

/* ------------------------------------------------------------------ */
/* 上电 / 待机序列（vendor 原样复刻）                                  */
/* ------------------------------------------------------------------ */

static int adc_init_one(struct mid_audio *priv, int c)
{
	return adc_write(priv, c, 0x00, 0x01);
}

static int adc_start_one(struct mid_audio *priv, int c)
{
	const u8 (*tbl)[2];
	int n, i, ret;

	if (seq_variant == 1) {
		tbl = es7243_start_seq_min;
		n = ARRAY_SIZE(es7243_start_seq_min);
	} else {
		tbl = es7243_start_seq;
		n = ARRAY_SIZE(es7243_start_seq);
	}

	for (i = 0; i < n; i++) {
		u8 reg = tbl[i][0];
		u8 val = tbl[i][1];

		/* 级联差异点：0x12 芯片 reg 0x08 的增益值改成 0x21 */
		if (reg == 0x08 && priv->adc[c].addr == ES7243_SYNC_ADDR)
			val = 0x21;

		ret = adc_write(priv, c, reg, val);
		if (ret)
			return ret;
	}

	/* 原厂驱动不写 0x0C（ES7243E 的 TDM_MODE/TDM_FLAG）；mainline 若要做
	 * 4ch TDM 级联才需要补写，具体值由 module param 在板上试。 */
	if (priv->adc[c].addr == ES7243_SYNC_ADDR && tdm_sync >= 0)
		return adc_write(priv, c, 0x0c, tdm_sync);
	if (priv->adc[c].addr != ES7243_SYNC_ADDR && tdm_first >= 0)
		return adc_write(priv, c, 0x0c, tdm_first);

	return 0;
}

static int adc_standby_one(struct mid_audio *priv, int c)
{
	int i, ret;

	for (i = 0; i < ARRAY_SIZE(es7243_standby_seq); i++) {
		ret = adc_write(priv, c, es7243_standby_seq[i][0],
				es7243_standby_seq[i][1]);
		if (ret)
			return ret;
	}
	return 0;
}

static int adc_power_up(struct mid_audio *priv)
{
	int c, ret;

	if (priv->adc_on)
		return 0;

	/* 芯片必须看到 MCLK 才应答 I2C：probe 里已常开，这里再兜一次底 */
	if (priv->mclk_clk) {
		clk_prepare_enable(priv->mclk_clk);
		usleep_range(20000, 25000);
	}

	for (c = 0; c < priv->num_adc; c++) {
		ret = adc_init_one(priv, c);
		if (ret)
			return ret;
	}

	/* 原厂 init 之后并没有显式延时，但 reset 位生效到 clock manager
	 * 可写之间有硬件状态机时间，给 10ms 保险。 */
	msleep(10);

	for (c = 0; c < priv->num_adc; c++) {
		ret = adc_start_one(priv, c);
		if (ret)
			return ret;
	}

	priv->adc_on = true;
	adc_dump(priv, "start");
	dev_info(priv->dev, "mic array ADC started (%d chips)\n", priv->num_adc);
	return 0;
}

static void adc_power_down(struct mid_audio *priv)
{
	int c;

	if (!priv->adc_on)
		return;

	for (c = 0; c < priv->num_adc; c++)
		adc_standby_one(priv, c);

	priv->adc_on = false;
	adc_dump(priv, "standby");
	dev_info(priv->dev, "mic array ADC standby\n");
}

/* ------------------------------------------------------------------ */
/* DAI                                                                */
/* ------------------------------------------------------------------ */

static int mid_set_fmt(struct snd_soc_dai *dai, unsigned int fmt)
{
	/* 本板 I2S0 始终是 bitclock / frame master（ES7148 只吃时钟，
	 * ES7243 也是从机），所以只接受 I2S + NB_NF + codec 全从。
	 * 但为了便于板上试参数，不匹配时只告警不报错。 */
	dev_info(dai->dev, "set_fmt 0x%x\n", fmt);
	return 0;
}

static int mid_set_sysclk(struct snd_soc_dai *dai, int clk_id,
			  unsigned int freq, int dir)
{
	struct snd_soc_component *comp = dai->component;
	struct mid_audio *priv = snd_soc_component_get_drvdata(comp);

	dev_info(dai->dev, "set_sysclk id=%d freq=%u dir=%d\n", clk_id, freq, dir);
	priv->mclk = freq;
	return 0;
}

static int mid_hw_params(struct snd_pcm_substream *substream,
			 struct snd_pcm_hw_params *params,
			 struct snd_soc_dai *dai)
{
	struct snd_soc_component *comp = dai->component;
	struct mid_audio *priv = snd_soc_component_get_drvdata(comp);
	unsigned int rate = params_rate(params);
	unsigned int ch = params_channels(params);

	dev_info(dai->dev, "%s rate=%u ch=%u fmt=%u mclk=%u\n",
		 substream->stream == SNDRV_PCM_STREAM_CAPTURE ? "capture" : "playback",
		 rate, ch, params_format(params), priv->mclk);

	if (substream->stream != SNDRV_PCM_STREAM_CAPTURE)
		return 0;

	/* rockchip_i2s 默认 bclk_ratio=64（2 槽 x 32bit），多声道会把帧截短，
	 * 必须在 CPU DAI 的 hw_params 之前改成 32*channels（codec 侧先于 cpu 侧） */
	if (auto_bclk_ratio) {
		struct snd_soc_pcm_runtime *rtd =
			snd_soc_substream_to_rtd(substream);
		struct snd_soc_dai *cpu_dai = snd_soc_rtd_to_cpu(rtd, 0);

		snd_soc_dai_set_bclk_ratio(cpu_dai, 32 * ch);
		dev_info(dai->dev, "bclk_ratio -> %u\n", 32 * ch);
	}

	if (trcm_txonly) {
		struct snd_soc_pcm_runtime *rtd =
			snd_soc_substream_to_rtd(substream);

		if (!rtd->dai_link->symmetric_rate) {
			rtd->dai_link->symmetric_rate = 1;
			dev_info(dai->dev, "forced dai_link->symmetric_rate (TRCM_TXONLY)\n");
		}
	}

	/* 采集方向：此刻 SoC 侧时钟已按 hw_params 落频，正适合给 ADC 上电 */
	return adc_power_up(priv);
}

static void mid_shutdown(struct snd_pcm_substream *substream,
			 struct snd_soc_dai *dai)
{
	struct snd_soc_component *comp = dai->component;
	struct mid_audio *priv = snd_soc_component_get_drvdata(comp);

	if (substream->stream == SNDRV_PCM_STREAM_CAPTURE)
		adc_power_down(priv);
}

static const struct snd_soc_dai_ops mid_dai_ops = {
	.set_fmt	= mid_set_fmt,
	.set_sysclk	= mid_set_sysclk,
	.hw_params	= mid_hw_params,
	.shutdown	= mid_shutdown,
};

/*
 * 一个 DAI 同时提供 playback 与 capture：
 *   playback —— ES7148 DAC，无寄存器，纯通路（约束与 es7134 一致：<= 48k）
 *   capture  —— 2xES7243 麦阵，最多 4ch
 * 这是 simple-audio-card 单 dai_link 同时得到播放与录音 PCM 的必要条件。
 */
static struct snd_soc_dai_driver mid_dai = {
	.name = "mid-audio-hifi",
	.playback = {
		.stream_name	= "Playback",
		.channels_min	= 1,
		.channels_max	= 2,
		.rates		= SNDRV_PCM_RATE_8000_48000,
		.formats	= SNDRV_PCM_FMTBIT_S16_LE |
				  SNDRV_PCM_FMTBIT_S24_LE |
				  SNDRV_PCM_FMTBIT_S32_LE,
	},
	.capture = {
		.stream_name	= "Capture",
		.channels_min	= 1,
		.channels_max	= 8,
		.rates		= SNDRV_PCM_RATE_8000_48000,
		.formats	= SNDRV_PCM_FMTBIT_S16_LE |
				  SNDRV_PCM_FMTBIT_S24_LE |
				  SNDRV_PCM_FMTBIT_S32_LE,
	},
	.ops = &mid_dai_ops,
};

static const struct snd_soc_component_driver mid_component = {
	.name = "rk3399-mid-audio",
};

/* ------------------------------------------------------------------ */
/* 平台驱动                                                           */
/* ------------------------------------------------------------------ */

static int mid_audio_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct mid_audio *priv;
	struct device_node *np;
	int i, ret;

	priv = devm_kzalloc(dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;
	priv->dev = dev;

	/* 两颗 ADC 通过 everest,adc = <&es7243_0>, <&es7243_1> 指过来；
	 * 我们自己从节点里取 i2c adapter + 地址，不依赖 i2c client 绑定。 */
	for (i = 0; i < MID_ADC_MAX; i++) {
		struct device_node *i2c_np;
		u32 addr;

		np = of_parse_phandle(dev->of_node, "everest,adc", i);
		if (!np)
			break;

		if (of_property_read_u32(np, "reg", &addr)) {
			dev_err(dev, "%pOF: no reg\n", np);
			of_node_put(np);
			return -EINVAL;
		}

		/* of_get_i2c_adapter_by_node() 要的是 i2c 控制器节点，
		 * 不是从设备节点 ⇒ 取父节点。 */
		i2c_np = of_get_parent(np);
		priv->adc[i].adap = of_get_i2c_adapter_by_node(i2c_np);
		priv->adc[i].addr = addr;
		of_node_put(i2c_np);
		of_node_put(np);

		if (!priv->adc[i].adap) {
			dev_err(dev, "adc[%d]@0x%02x: i2c adapter not found\n",
				i, addr);
			return -EPROBE_DEFER;
		}
		dev_info(dev, "adc[%d]: i2c-%d addr 0x%02x\n", i,
			 priv->adc[i].adap->nr, priv->adc[i].addr);
	}
	priv->num_adc = i;

	if (!priv->num_adc) {
		dev_err(dev, "no everest,adc phandles\n");
		return -EINVAL;
	}

	platform_set_drvdata(pdev, priv);

	/*
	 * 取 i2s0 的 MCLK（DTS: clocks = <&cru SCLK_I2S0>, clock-names="mclk"），
	 * probe 时就打开并常开：ES7243 在没看到 MCLK 之前不应答 I2C，而 ASoC 的
	 * hw_params 里 codec 先于 cpu dai 执行，此时 rockchip_i2s 的 runtime_resume
	 * 未必已经 enable 自己的 mclk ⇒ 不常开就必然 -ENXIO。
	 */
	priv->mclk_clk = devm_clk_get(dev, "mclk");
	if (IS_ERR(priv->mclk_clk)) {
		ret = PTR_ERR(priv->mclk_clk);
		if (ret == -EPROBE_DEFER)
			return ret;
		dev_warn(dev, "no mclk clock (%d), ADC may not answer I2C\n", ret);
		priv->mclk_clk = NULL;
	} else {
		ret = clk_prepare_enable(priv->mclk_clk);
		if (ret)
			dev_warn(dev, "mclk enable failed: %d\n", ret);
		else
			dev_info(dev, "mclk %u Hz enabled\n",
				 clk_get_rate(priv->mclk_clk));
	}

	ret = devm_snd_soc_register_component(dev, &mid_component, &mid_dai, 1);
	if (ret) {
		dev_err(dev, "register component failed: %d\n", ret);
		return ret;
	}

	if (power_on_probe) {
		ret = adc_power_up(priv);
		if (ret)
			dev_err(dev, "power_on_probe failed: %d\n", ret);
	}

	dev_info(dev, "rk3399-mid audio component registered\n");
	return 0;
}

static const struct of_device_id mid_audio_of_match[] = {
	{ .compatible = "rockchip,rk3399-mid-audio" },
	{ }
};
MODULE_DEVICE_TABLE(of, mid_audio_of_match);

static struct platform_driver mid_audio_driver = {
	.probe = mid_audio_probe,
	.driver = {
		.name = "rk3399-mid-audio",
		.of_match_table = mid_audio_of_match,
	},
};
module_platform_driver(mid_audio_driver);

MODULE_DESCRIPTION("RK3399-MID composite audio codec (ES7148 play + 2x ES7243 mic array capture)");
MODULE_AUTHOR("rk3399-mid project");
MODULE_LICENSE("GPL");
