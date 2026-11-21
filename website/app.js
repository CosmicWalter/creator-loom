"use strict";
const demos = {
  story: {
    kind: "有声故事 · BOOKCAST",
    title: ["让灯塔的故事，", "被听见，也被看见。"],
    description: "把已授权的章节变成口播稿、封面、配音和视频。上下文与连续性说明随计划保存，审核后再进入下一集。",
    link: "docs/books-and-series.md", linkText: "了解连续创作",
    steps: [["文稿改编", "文字模型 · 任务与来源"], ["封面设计", "图像模型或本地图形工具"], ["生成旁白", "语音服务 · 音色授权"], ["视频合成", "本机 FFmpeg · 审核交付"]],
    boundary: "当前配方输出静态配图视频；多镜头剪辑可通过本机剪辑台或 CLI 时间线完成。",
  },
  writing: {
    kind: "文字创作 · ARTICLE / NOVEL",
    title: ["先理清故事，", "再把每一段写好。"],
    description: "从一篇文章开始，或导入已授权的 TXT / EPUB。小说配方先做大纲，再写章节；偏好、原文与已接受的连续性说明进入冻结计划。",
    link: "docs/books-and-series.md", linkText: "了解书籍与章节",
    steps: [["明确创作要求", "语言 · 偏好 · 隐私 · 预算"], ["选择任务模型", "大纲与章节分别决策"], ["保存实际产物", "来源与产物哈希绑定"], ["审核与修改练习", "记录改稿与自评理由"]],
    boundary: "文章配方直接生成草稿；小说配方包含大纲和章节。丰富角色记忆仍在路线图中。",
  },
  visual: {
    kind: "图像与图文 · COVER / MEME",
    title: ["为你的表达，", "找到一个视觉入口。"],
    description: "用本地图形工具体验无需密钥的封面制作，或接入自己的图像接口。图文配方先写创意文案，再把文案作为图像制作的输入。",
    link: "README.md#接入自己的模型", linkText: "了解模型接入",
    steps: [["写下视觉要求", "主题与语言"], ["检查工具能力", "本地图形或图像模型"], ["生成封面或图文", "保留模型与计划快照"], ["检查画面与权利", "审核后导出实际产物"]],
    boundary: "本地封面是模板图形设计，不是 AI 绘画。ComfyUI、角色参考一致性与生成式视频尚未接入。",
  },
  edit: {
    kind: "本机剪辑 · EDITING ROOM",
    title: ["让每个镜头，", "接住下一句话。"],
    description: "把已审核的图片、视频与音频排成有节奏的作品。裁切视频入点、加入图片缩放、混合旁白与音乐，为明确的时刻写上字幕。",
    link: "docs/timeline.md", linkText: "了解剪辑台与时间线",
    steps: [["引用已审核素材", "图片 · 片段 · WAV 音轨"], ["安排镜头与字幕", "时长 · 入点 · 缩放 · 音量"], ["逐镜头审核封存", "修改保留历史版本"], ["本机制作与成片审核", "MP4 · SRT · 编辑清单"]],
    boundary: "本机剪辑台提供镜头列表、时长与音轨表单，仍待浏览器交互验收。字幕为编辑者提供的时间，不是自动语音对齐。",
  },
};
const tabs = [...document.querySelectorAll("[data-demo]")];
function activate(tab) {
  const demo = demos[tab.dataset.demo];
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute("aria-selected", String(selected));
    item.tabIndex = selected ? 0 : -1;
  }
  document.querySelector("#demo-panel").setAttribute("aria-labelledby", tab.id);
  document.querySelector("#demo-kind").textContent = demo.kind;
  const title = document.querySelector("#demo-title");
  title.replaceChildren(document.createTextNode(demo.title[0]), document.createElement("br"), document.createTextNode(demo.title[1]));
  document.querySelector("#demo-description").textContent = demo.description;
  document.querySelector("#demo-doc").href = "https://github.com/CosmicWalter/creator-loom/blob/main/" + demo.link;
  document.querySelector("#demo-doc").textContent = demo.linkText;
  const list = document.querySelector("#demo-steps");
  list.replaceChildren(...demo.steps.map(([name, detail]) => {
    const li = document.createElement("li"), span = document.createElement("span"), small = document.createElement("small");
    span.textContent = name; small.textContent = detail; li.append(span, small); return li;
  }));
  document.querySelector("#demo-boundary").textContent = demo.boundary;
}
for (const tab of tabs) {
  tab.addEventListener("click", () => activate(tab));
  tab.addEventListener("keydown", (event) => {
    const index = tabs.indexOf(tab);
    let target;
    if (event.key === "ArrowRight") target = tabs[(index + 1) % tabs.length];
    if (event.key === "ArrowLeft") target = tabs[(index + tabs.length - 1) % tabs.length];
    if (event.key === "Home") target = tabs[0];
    if (event.key === "End") target = tabs[tabs.length - 1];
    if (target) { event.preventDefault(); activate(target); target.focus(); }
  });
}
document.querySelector("#copy-install").addEventListener("click", async () => {
  const status = document.querySelector("#copy-status");
  try {
    await navigator.clipboard.writeText(document.querySelector("#install-command").textContent);
    status.textContent = "命令已复制。请在本机终端中查看并运行。";
  } catch {
    status.textContent = "浏览器未允许复制。可以选中上面的命令手动复制。";
  }
});
