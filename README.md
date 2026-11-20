# Creator Loom

**An open content creation agent that explains its choices and learns from reviewed outcomes.**

面向文字、图片、音频、视频的开源创作 Agent。目标是把创作、模型决策、个人偏好和技术迭代放进一个可检查的闭环，让作品和创作者一起进步。

**状态：早期可运行原型，不是已经达到行业标杆的成品。** Python 3.11+，核心零运行时依赖，MIT 开源。当前入口是 CLI；没有网页工作台、平台投稿、通用自主工具执行或自动训练模型权重。

## 立即运行

```sh
git clone https://github.com/CosmicWalter/creator-loom.git
cd creator-loom
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

# 不需要密钥或模型：生成真实的本地图形封面，不冒充 AI 绘画。
loom plan '海边的阅读时光' --format cover --local-only --budget 0
loom create '海边的阅读时光' --format cover --local-only --budget 0
# 用上一条输出的 run 值替换 RUN_ID。
loom execute RUN_ID
loom inspect RUN_ID
loom approve RUN_ID
```

运行目录为 `data/`，默认不提交。封面同时输出可编辑 SVG 和用于合成视频的 PPM 背景；当前 PPM 只包含图形，标题排版在 SVG 中。`approve` 只记录本机审核，不会发布到社交平台。

## 接入自己的模型

复制 `examples/models.json` 为 `config.local.json`，填写实际模型名和接口地址，修改相应条目的 `enabled` 为 `true`。密钥只从指定环境变量读取，不写进模型卡或运行记录。示例质量、费用、延迟是演示估计，不是已测性能或供应商报价。

```sh
loom --config config.local.json models
loom --config config.local.json plan '一段关于好奇心的原创故事' --format article
loom --config config.local.json create '一段关于好奇心的原创故事' --format article
loom --config config.local.json execute RUN_ID
```

支持以下明确的 HTTP 契约，兼容性仍需针对所用服务验收：

| Adapter | 接口与产物 | 当前边界 |
| --- | --- | --- |
| `chat` | `/chat/completions` → Markdown | 非流式，最多请求 2048 输出 token |
| `image` | `/images/generations` → base64 PNG | 单张 1024×1024；不自动下载返回 URL |
| `speech` | `/audio/speech` → WAV | 默认 `alloy`；不包含声音克隆 |
| `cover` | 本地图形 → SVG + PPM | 模板设计，不是生成式模型 |
| `render` | 图片 + 旁白 → H.264/AAC MP4 | 系统需安装 FFmpeg；静态配图视频，最长 10 分钟 |

本地 HTTP 模型只能使用 loopback；远端接口要求 HTTPS，拒绝 URL 内凭据和重定向。`--local-only` 禁止向远端模型发内容，但无法证明 loopback 服务内部没有再调用云服务。

## 创作流程

| Format | 流程 |
| --- | --- |
| `article` | 主题 → 文章 |
| `novel` | 主题 → 故事大纲 → 开篇章节 |
| `cover` | 主题 → 封面 |
| `podcast` | 主题 → 口播文稿 → 配音 |
| `bookcast` / `talkshow` | 主题 → 文稿 + 封面 → 配音 → 配图视频 |
| `meme` | 主题 → 文案 → 图像 |

这些是固定、有依赖关系的流程，还不是自然语言自动拆解任意任务的规划器。`bookcast` 当前生成主题口播，不支持导入全文、自动分集或有声书连续剧情；`meme` 当前不做影视人物替换。已有制作工具的经验如何迁入，见 [来源与迁移](docs/project-inventory.md)。

## 模型决策

每个步骤保存模型快照、候选分数、排除理由和偏好快照。先按能力、隐私、预算估计、语言、输入上限、延迟目标和凭据可用性过滤；再以质量 75%、费用 15%、速度 10% 排序。

质量使用模型卡先验与**该 profile、该模态**的实际人工评分，先验相当于四次观察，避免一次点击覆盖所有历史。同一产物重复评分会更新记录，不会增加样本。现有计划不会因后来改了配置、偏好或评分而悄悄变化。

`--budget` 和 `--max-latency` 是配置估计的计划约束，**不是实际账单或运行时长的保证**。尚未实现供应商账单核对、token 计价、汇率或钱包硬上限。模型卡估计需使用者自行校准。

```sh
loom preferences default --set '{"tone":"清晰、克制","audience":"刚开始创作的人"}'
loom feedback RUN_ID draft 0.8
loom forget default
```

`forget` 删除偏好与用于路由的反馈，不删除作品、评测或审计日志。当前 profile 是本机偏好分组，不是隔离租户或认证账号。

## 学习与迭代

```sh
# 读取公开 release feed；不自动安装或运行其中任何内容。
loom discover https://github.com/Comfy-Org/ComfyUI/releases.atom

# 人工整理新方法为编辑指导，保留证据链接。
loom propose concrete-detail --source https://example.com/research \
  --guidance '用可观察的具体细节替换空泛形容词，同时保留原意。'

# 同一主题创建 baseline 与实验作品；至少三个不同主题，分别审核。
loom --config config.local.json create '实验主题一' --format article
loom --config config.local.json create '实验主题一' --format article --technique concrete-detail
# execute → 人工检查产物 → approve；按文档记录成对评分。
loom evaluate concrete-detail --pairs evaluation.local.json
loom promote concrete-detail
loom rollback concrete-detail
```

只有经过实际产物配对、来源检查、评分门槛和显式启用，编辑方法才影响后续创作。这个机制更新的是提示方法与路由反馈，**不等于已经实现自主搜集整个互联网、修改自身代码或训练基础模型**。人工评分不是统计显著的质量证明。详细协议见 [学习与评测](docs/learning.md)。

## 可靠性与验证

远端调用开始前保存状态；超时、进程中断、响应解析失败等都可能已经产生费用，因此结果不明的运行不能自动重放。失败时保留已完成步骤和事件，以便核对供应商。暂不提供跨进程断点恢复的完整协调器。

审核绑定所有产物的 SHA256；产物被修改后拒绝审核。密钥、原项目账号、私有素材和部署配置不迁入仓库。单用户本机工具，不应当直接当作公网多租户服务。

```sh
python -m unittest discover -s tests -v
python scripts/check_publication.py
```

测试包括真实 loopback HTTP 契约、真实 FFmpeg 合成、并发领取、防重放、反馈影响路由、偏好隔离、学习评测与回滚。推理服务在测试中是明确标注的模拟服务，不能据此声称真实模型音质、画质或写作质量通过验收。

接下来按 [路线图](ROADMAP.md) 继续迭代；[行业对标](docs/landscape.md) 是产品方向比较，不是已经胜过其他产品的性能榜单。
