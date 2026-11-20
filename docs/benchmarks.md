# 模型对照评测

该 CLI 流程比较一个明确任务的两个已配置模型，例如 `article:draft` 或 `novel:chapter`。它不修改模型权重，不自动激活新技术，也不代表已经完成真实供应商质量验证。

## 准备

配置两个可用模型，并准备 6–50 个不同的、已获授权的 brief。参考 [原创示例](../examples/benchmark.json)，把模型 ID 替换为配置中的实际 ID。所有 case 必须使用相同 profile 和 format。可选择 `book`、`unit` 和 `continuity`，其源书籍必须已通过正常导入流程保存。

```sh
loom --config config.local.json benchmark-new writing-trial --spec examples/benchmark.json
loom benchmark-inspect writing-trial
```

创建时即持久化随机的一半开发集与其余留出集、模型卡、偏好、技术快照、源上下文和各 case 的 A/B 映射。此后修改配置不会改变已冻结计划。每个目标模型必须满足各自完整前缀计划的预算、输入容量与延迟估计约束；费用只是在配置估计下的保守总和，候选前缀实际复用，不是等额支出试验或供应商账单。

## 开发集

从 inspect 的开发集 case 中逐个生成 baseline，再生成 candidate：

```sh
loom benchmark-generate writing-trial case-1 baseline
loom benchmark-generate writing-trial case-1 candidate
loom benchmark-packet writing-trial case-1
```

`case-1` 只是示例，实际分区由创建时的随机划分决定。重复 generate 返回原运行状态，不重新调用推理。计划只执行到目标步骤：例如配音对照不会继续生成影片。候选运行复制 baseline 的真实上游产物并校验哈希，只有目标步骤重新推理。复用的步骤不会重复计入运行测量。

异步配音返回 `waiting_external` 时，对输出的运行 ID 使用 `loom wait RUN_ID` 或 `loom resume RUN_ID`；未知外部提交仍必须按原有 MediaFlow 流程显式核对，不自动重试。

评审 ZIP 保存在本机运行目录。它包含 A/B 目标文件、目标直接依赖的共享创作文件、最少的 brief 内容和评分模板，不包含模型或运行映射、端点、profile、用量、操作回执。源书籍适配会附带源片段与已接受的连续性说明。依照目标媒介检查合题性、清晰度和创作技法，以同一量表给 A/B 分别打 0–1 分并说明理由：

```sh
loom benchmark-review writing-trial case-1 --a 0.6 --b 0.7 --rationale '说明两件实际产物与题目及媒介要求的差异'
```

评分记录后不可修改。所有开发集 case 评审结束后：

```sh
loom benchmark-seal writing-trial
```

## 留出集、报告与校准

封存前，留出集不能生成或评审；普通 execute 也不能绕过 benchmark-generate。封存后按相同步骤完成所有留出集 case，再生成报告：

```sh
loom benchmark-report writing-trial
```

报告解开 A/B 映射，分别列出开发集与留出集的逐对评分、平均差、胜负和平局。单侧符号检验忽略平局，检验方向为 candidate 优于 baseline；小样本、多次试验、评分依赖和选题偏差均限制解释，不可据此宣称总体质量领先。开发集与留出集不会合并为一项质量结论。

如果决定用留出集评分改进后续路由，先查看并通过正常 approve 审核每个留出集运行的实际产物，然后：

```sh
loom approve HOLDOUT_BASELINE_RUN
loom approve HOLDOUT_CANDIDATE_RUN
# 对所有留出集运行重复审核后：
loom benchmark-calibrate writing-trial
```

校准会再次校验产物，仅写入留出集目标步骤的 profile、format:stage、模型 ID 与后端签名隔离反馈；重复校准不会增加样本数。普通 feedback 不接受评测运行，避免开发集评分或人工覆盖污染校准。执行时延、可靠性等操作测量仍按正常运行记录，不属于留出集质量评分。

## 解释边界与隐私

A/B 隐藏只作用于评审展示。本机所有者能读取状态库及冻结计划，生成内容也可能自行提及模型身份；系统没有安全隔离评审者，也不能证明评审独立或选题互不相关。不同标题不保证内容独立。测试中的产物与评分都是模拟数据，没有真实模型排名或创作者技能提升结论。

分享评审包前，应核实源内容授权并检查创作文本、音视频和内嵌元数据。剔除操作记录和中和 ZIP 时间戳并不会清除模型生成文件自身可能携带的信息；评审包不会自动上传。该版本没有工作台评测界面，也未完成浏览器视觉验收。
