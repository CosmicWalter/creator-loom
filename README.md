# Creator Loom

**An open content creation agent that explains its choices and learns from reviewed outcomes.**

[项目官网](https://cosmicwalter.github.io/creator-loom/) · [本机工作台](docs/workbench.md) · [路线图](ROADMAP.md)

面向文字、图片、音频、视频的开源创作 Agent。目标是把创作、模型决策、个人偏好和技术迭代放进一个可检查的闭环，让作品和创作者一起进步。

**状态：早期可运行原型，不是已经达到行业标杆的成品。** Python 3.11+，核心零运行时依赖，MIT 开源。提供 CLI 和仅本机访问的网页工作台；尚无平台投稿、通用自主工具执行或自动训练模型权重。

## 立即运行

```sh
git clone https://github.com/CosmicWalter/creator-loom.git
cd creator-loom
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

# 打开本地工作台；访问码只由启动终端提供，不写入前端文件。
loom serve --open
```

工作台支持方案预览、按冻结方案制作、作品预览与审核、交付包、书籍／连续作品、学习收件箱和文字修改练习。默认使用无需密钥的本地图形封面体验；其他创作形式读取启动时配置的模型。可用 `loom --config config.local.json serve --open` 加载自己的模型配置。界面与本机访问边界见 [工作台说明](docs/workbench.md)。

也可以继续使用 CLI：

```sh

# 不需要密钥或模型：生成真实的本地图形封面，不冒充 AI 绘画。
loom plan '海边的阅读时光' --format cover --local-only --budget 0
loom create '海边的阅读时光' --format cover --local-only --budget 0
# 用上一条输出的 run 值替换 RUN_ID。
loom execute RUN_ID
loom inspect RUN_ID
loom approve RUN_ID
```

运行目录为 `data/`，默认不提交。封面同时输出可编辑 SVG 和用于合成视频的 PPM 背景；当前 PPM 只包含图形，标题排版在 SVG 中。`approve` 只记录本机审核，不会发布到社交平台。

## 证据驱动的研究实验

学习雷达可选择公开资料版本，由已配置的文字模型生成带原文引用的编辑方法与测试题。结构和引用检查通过后，还需人工审核产物、许可与兼容性，再预先划分开发集和留出集进行同模型配对实验。采用只使用已封存的留出评分，显式启用后仅作用于所选任务；保留其他任务的方法及回滚。见 [研究实验室](docs/research-lab.md)。当前测试使用模拟推理，不代表已验证真实创作收益。

## 授权素材与音乐改编

工作台「素材与音乐」可导入你有权使用的图片、音频和视频。规范化产物须审核后才能进入剪辑，公开署名与许可会随素材包和时间线交付保留。参考音频支持可复现的裁切、独立变速／移调及磁带式联动处理。

音乐方案配方使用文字模型生成歌词和音乐方向，**不听取参考音频、不生成歌曲、不自动操作 Suno**。审核方案后可显式准备人工交接包，外部制作完成后导入、试听并采纳实际音频。来源链接属于用户报备，供应商生成回执仍未接入。见 [音乐与素材流程](docs/music.md)。

## 多镜头剪辑与字幕

网页剪辑台与 CLI 时间线可将已审核的图像、视频片段和旁白组合为多镜头作品：支持视频入点裁切、图片居中缓慢缩放、旁白与音乐混合，以及可选择的字幕轨和 SRT。镜头逐项审核、成片再次审核后才能导出；修改创建新版本，保留旧版。使用方式见 [时间线说明](docs/timeline.md)。网页剪辑台支持素材预览、镜头排序、时长与入点、音轨与字幕编辑、版本审核和后台渲染；浏览器实际交互与视觉验收仍待完成。

## 对照评测与模型校准

可为一个明确任务建立冻结的双模型对照：预先划分开发集和留出集，以随机 A/B 标签评审，只有封存开发集后才能生成留出集。候选模型复用相同上游素材；评分不可覆盖。审核后的留出集评分可显式加入任务及后端隔离的路由反馈。使用步骤与局限见 [模型评测](docs/benchmarks.md)。当前验证使用模拟产物，不代表真实模型的质量结论。

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
| `chat` | `/chat/completions` → Markdown | 非流式，默认 2048 输出 token / 9000 字符；两项可配置 |
| `image` | `/images/generations` → base64 PNG | 单张 1024×1024；不自动下载返回 URL |
| `speech` | `/audio/speech` → PCM WAV | `voice` 可配置，默认 `alloy`；不包含声音克隆 |
| `mediaflow` | 本机 MediaFlow 任务 API → 分段 PCM WAV + 时间段 JSON | IndexTTS、已授权参考音色；记录任务号，支持暂停与恢复 |
| `cover` | 本地图形 → SVG + PPM | 模板设计，不是生成式模型 |
| `render` | 图片 + 旁白 → H.264/AAC MP4 | 系统需安装 FFmpeg/FFprobe；静态配图视频，旁白超过 10 分钟会拒绝而非截断 |

本地 HTTP 模型只能使用 loopback；远端接口要求 HTTPS，拒绝 URL 内凭据和重定向。`--local-only` 禁止向远端模型发内容，但无法证明 loopback 服务内部没有再调用云服务。

## 接入本机 MediaFlow 配音

如已安装并启动独立的 MediaFlow 服务，可上传已授权参考音色，然后把返回的素材 ID 填入示例模型卡的 `voice`，确认 `voice_authorized: true` 并启用该卡：

```sh
loom mediaflow-upload-voice reference.wav --voice-authorized
loom --config config.local.json create '一段原创故事' --format podcast --local-only
loom --config config.local.json execute RUN_ID
# waiting_external 表示远端任务尚未交付；已完成文稿不会重做。
loom resume RUN_ID
loom wait RUN_ID --timeout 300
loom remote-ops RUN_ID
```

旁白按模型卡的 `segment_chars` 分段，默认每段最多 150 字；每段保留冻结请求、幂等键、远端任务号和音频摘要。已知任务恢复时查询原任务，下载失败只重试可重复读取的 MediaFlow 文件。提交响应不明时停止重发，需显式核对并绑定已有任务号。音频拼接后可继续原来的配图视频步骤。

`timings.json` 是按每段实际音频长度生成的时间范围，不是逐字对齐。MediaFlow 仍是独立可选服务，此仓库不包含其代码、模型权重或已有账号。授权、异步状态、核对命令和验收边界见 [MediaFlow 接入](docs/mediaflow.md)。

## 创作流程

| Format | 流程 |
| --- | --- |
| `article` | 主题 → 文章 |
| `novel` | 主题 → 故事大纲 → 开篇章节 |
| `cover` | 主题 → 封面 |
| `podcast` | 主题 → 口播文稿 → 配音 |
| `bookcast` / `talkshow` | 主题 → 文稿 + 封面 → 配音 → 配图视频 |
| `meme` | 主题 → 文案 → 图像 |

这些是固定、有依赖关系的流程，还不是自然语言自动拆解任意任务的规划器。现在可以导入已授权的 TXT／未加密 EPUB，按章节切分为有长度上限的单元，再逐集改编为文章、小说、口播或配图视频；连续性笔记由用户审核后维护。`meme` 当前不做影视人物替换。已有制作工具的经验如何迁入，见 [来源与迁移](docs/project-inventory.md)。

## 长文本与连续创作

仓库附带原创 MIT 样本文本，可先验证导入，不需要模型：

```sh
loom book-import examples/lighthouse.txt --title '灯塔的信号' --rights owned
loom book-inspect BOOK_ID
loom book-inspect BOOK_ID --unit 0
```

填写真实模型配置后，可以按单段创作，也可以建立逐集审核的系列：

```sh
loom --config config.local.json create '忠于原文，改编成清晰的口播' \
  --format podcast --book BOOK_ID --unit 0

loom series-new BOOK_ID '保留人物与事件顺序，改编为中文有声故事' --format bookcast
loom --config config.local.json series-next SERIES_ID
# inspect → execute → 人工检查文稿、配音与视频 → approve RUN_ID
loom series-accept SERIES_ID RUN_ID --base-version 1 \
  --continuity 'Rowan 在灯塔看到蓝色信号；尚未与船上的人见面。'
loom --config config.local.json series-next SERIES_ID
```

`series-next` 只创建当前单元的计划；重复或并发调用会复用待处理任务。只有该集实际产物通过 `approve`，再显式 `series-accept`，才推进原文游标并更新版本。下一集冻结已接受的连续性笔记；原任务不会自动重跑。`--start-unit` 可在建立系列时选择起点，方便检查前言等材料后再决定从哪里开始。

导入要求声明 `owned`、`licensed` 或 `public-domain`，该声明不是权属核验。原文件和文本只存入本机数据目录，不保存导入文件名与来源路径；正文、授权说明及连续性笔记会按所选模型配置用于生成，敏感内容应使用已核验的本地服务。格式、长度边界、拒绝与重新制作流程见 [书籍与连续创作](docs/books-and-series.md)。

## 模型决策

每个步骤保存模型快照、候选分数、排除理由和偏好快照。先按能力、隐私、预算估计、语言、输入上限、延迟目标和凭据可用性过滤；再以质量 75%、费用 15%、速度 10% 计分，并用观察到的执行可靠性调整得分。联合搜索整条流程的模型组合，在总预算和总延迟估计内最大化各步得分之和，避免前一步花光预算。每个上游文字步骤保留所选模型的 `max_output_chars`，连同实际提示包装计入下游输入容量；超出字符上限的模型响应会被拒绝，不会截断后冒充完整文稿。分数以同一总预算归一化；最多检查一百万种组合，超限会要求缩小启用模型集合，不会静默退回近似结果。

质量先验按 `task_quality` 的 `格式:阶段` → 格式 → 通用 `quality` 查找。例如可分别为 `novel:outline` 和 `novel:chapter` 配置不同擅长程度。然后结合**该 profile、该任务、该模型后端与生成配置**的人工评分，先验相当于四次观察。文章的反馈不会影响小说；替换模型、接口地址、音色或输出限制后也不会继承旧后端的成绩。同一产物重复评分会更新记录，不会增加样本。现有计划不会因后来改了配置、偏好或评分而悄悄变化。

调用耗时和成功/不确定结果按同样范围记录。延迟估计取配置值与带四次先验的成功耗时均值中的较大值，避免少数快速样本导致过度乐观。可靠性用四次成功先验平滑；不确定结果会降低得分，但不会自动重试原请求。这些是可检查的决策启发式，不是对最优创作质量的保证。

`--budget` 和 `--max-latency` 是配置估计的计划约束，**不是实际账单或运行时长的保证**。尚未实现供应商账单核对、缓存等特殊计费、汇率或钱包硬上限。模型卡估计需使用者自行校准。

可使用 `loom metrics --profile default` 或 `loom metrics --run RUN_ID` 查看已记录步骤的耗时、结果和 token 用量。文字模型返回 `usage.prompt_tokens` 与 `usage.completion_tokens` 时只保存这两个计数；其余供应商字段不会进入记录。如果配置了 `input_price_per_million` 和 `output_price_per_million`，则按**运行时冻结的模型卡费率**计算 token 费用估计。费率、`cost` 和 `budget` 应使用同一计价单位。缺失或无效用量保留“未报告/未知”，不会填成零费用。`priced_steps` 与 `unpriced_steps` 显示覆盖范围；图片、语音和本地工具当前不做 token 费用估计。

```sh
loom preferences default --set '{"tone":"清晰、克制","audience":"刚开始创作的人"}'
loom feedback RUN_ID draft 0.8
loom forget default
```

`forget` 删除偏好、用于路由的反馈与调用指标，阻止这些历史继续影响选择；不删除工作台方案与操作记录、远端任务凭据、研究订阅与资料、导入书籍、系列连续性笔记、作品、作品内保存的指标、评测或审计日志。当前 profile 是本机偏好分组，不是隔离租户或认证账号。

## 创作者练习

完成作品后，可按各模态的编辑量表审阅，保存一次明确的修改，并记录修改前后的同量表评分：

```sh
loom coach RUN_ID
# 人工保存修改后的文稿为 revision.md，再记录具体的编辑理由。
loom practice RUN_ID draft --revision revision.md --dimension clarity \
  --before 0.4 --after 0.7 --rationale '补充一个具体例子，让开头的核心观点更容易理解。'
loom progress default
```

练习保存原稿摘要、修改稿副本、量表维度和评分理由，拒绝把未改动的稿件算作练习。不同 profile 的记录分开统计。评分属于人工自评，不是已验证的学习增益，也不证明产品使用户能力提高；后续需要盲评和长期样本。`forget` 不删除练习，当前如需彻底删除所有本机数据，需自行备份后删除数据目录。

## 学习与迭代

可以保存公开 RSS／Atom 订阅，让前台 Worker 按各订阅的间隔收集资料，再从收件箱中评审新方法：

```sh
loom source-add comfyui https://github.com/Comfy-Org/ComfyUI/releases.atom \
  --keyword video --keyword audio --keyword image --interval 21600
loom research-refresh comfyui
loom research-inbox
loom research-show ITEM_ID
loom research-propose ITEM_ID feed-technique --base-revision 1 \
  --note '已阅读这条资料，准备验证其中一个具体且适用于当前任务的编辑方法。' \
  --guidance '填写经过人工整理、可在现有创作流程中验证的具体方法。'

# 默认只检查一次到期订阅；--watch 才会持续前台轮询，不安装后台服务。
loom research-worker
loom research-worker --watch
```

相同链接会去重；内容变更保留修订，已有忽略决定和实验提案不会被覆盖。`research-inbox --state changed` 查看评审后变化的资料。相关性是标题／摘要的字面关键词匹配，显示命中词，不声称自动识别技术突破。提案保存该版本的证据、摘要和评审理由，仍须通过下面的实验与启用关卡。

默认使用 Python HTTPS；若本机 Python 缺少系统信任的 CA，可显式选择 `--transport curl`（用于 `discover`、`source-add` 或 `source-set`）。该模式使用系统 curl，跳过个人 curl 配置，保留证书校验、禁止跳转并限制响应大小。订阅、版本、失败重试与信任边界见 [研究收件箱](docs/research-inbox.md)。

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

远端调用开始前保存状态；超时、进程中断、响应解析失败等都可能已经产生费用，因此结果不明的运行不能自动重放。失败时保留已完成步骤和事件，以便核对供应商。MediaFlow 配音可在进程锁确认没有本端执行器后，从已记录的异步检查点恢复；未知的同步模型调用仍不能自动重放。这不是适用于任意提供商的完整恢复协调器。

审核绑定所有产物的 SHA256；产物被修改后拒绝审核。密钥、原项目账号、私有素材和部署配置不迁入仓库。单用户本机工具，不应当直接当作公网多租户服务。

```sh
python -m unittest discover -s tests -v
node --check creator_loom/static/app.js
python scripts/check_publication.py
```

测试包括真实 loopback HTTP 契约、真实 FFmpeg 合成、并发领取、防重放、反馈影响路由、偏好隔离、学习评测与回滚。推理服务在测试中是明确标注的模拟服务，不能据此声称真实模型音质、画质或写作质量通过验收。

接下来按 [路线图](ROADMAP.md) 继续迭代；[行业对标](docs/landscape.md) 是产品方向比较，不是已经胜过其他产品的性能榜单。
