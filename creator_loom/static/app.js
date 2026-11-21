"use strict";
const $ = (s) => document.querySelector(s);
const state = {
  view: "create",
  overview: null,
  profile: "default",
  draft: null,
  createKey: null,
};
const watchedActions = new Set();
const formats = {
  article: "文章",
  song: "歌词与音乐方案",
  research: "资料综合提案",
  novel: "小说改编",
  cover: "本地图形封面",
  podcast: "播客口播",
  bookcast: "有声故事视频",
  talkshow: "单口节目",
  meme: "图文创意",
};
const statuses = {
  ready: "待制作",
  executing: "制作中",
  waiting_external: "等待远端任务",
  needs_review: "待审核",
  approved: "已审核",
  blocked: "需要处理",
  cancelled: "已取消",
};
const stages = {
  draft: "文章",
  lyrics: "歌词方案",
  synthesis: "证据综合",
  direction: "音乐方向",
  imported: "授权导入",
  outline: "故事大纲",
  chapter: "章节正文",
  script: "口播文稿",
  caption: "创意文案",
  cover: "封面设计",
  narration: "配音",
  film: "视频合成",
};
const dimensions = {
  clarity: "表达清晰",
  specificity: "具体细节",
  structure: "内容结构",
  integrity: "来源与准确性",
  hierarchy: "视觉层级",
  legibility: "可读性",
  consistency: "风格一致",
  intelligibility: "听感清晰",
  pacing: "节奏",
  coherence: "声画连贯",
  delivery: "交付表现",
};
const reviewQuestions = {
  clarity: "读者读一遍后，能否说清楚核心观点？",
  specificity: "哪一处空泛描述可以替换为具体、可观察的例子？",
  structure: "每一段是否服务于创作要求，前后推进是否清楚？",
  integrity: "来源和素材是否有权使用？事实、虚构与 AI 辅助内容是否需要说明？",
  hierarchy: "视线最先落在哪里，它是否服务于作品主题？",
  legibility: "在实际展示尺寸下，标题与主体是否清晰可辨？",
  consistency: "人物、声音或视觉风格是否保持一致？",
  intelligibility: "正常播放速度下，每一句话是否都能听清？",
  pacing: "哪里需要停顿、缩短句子或调整剪辑节奏？",
  coherence: "画面是否准确支持正在讲述的内容？",
  delivery: "画幅、播放与音量是否适合最终交付场景？",
};
function node(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function add(parent, ...children) {
  for (const c of children) if (c) parent.append(c);
  return parent;
}
function button(text, fn, cls = "") {
  const b = node("button", cls, text);
  b.type = "button";
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await fn();
    } catch (e) {
      toast(e.message);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}
function field(label, input) {
  const l = node("label", "", label);
  l.append(input);
  return l;
}
function input(value = "", type = "text") {
  const n = node("input");
  n.type = type;
  n.value = value;
  return n;
}
function textarea(value = "") {
  const n = node("textarea");
  n.value = value;
  return n;
}
function select(options, value) {
  const n = node("select");
  for (const [v, t] of options) {
    const o = node("option", "", t);
    o.value = v;
    n.append(o);
  }
  if (value !== undefined) n.value = value;
  return n;
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  clearTimeout(state.toast);
  state.toast = setTimeout(() => ($("#toast").hidden = true), 5500);
}
async function api(path, body, key) {
  const options = { credentials: "same-origin", headers: {} };
  if (body !== undefined) {
    options.method = "POST";
    options.headers = {
      "Content-Type": "application/json",
      "X-Loom-Request": "1",
    };
    if (key) options.headers["Idempotency-Key"] = key;
    options.body = JSON.stringify(body);
  }
  const r = await fetch(path, options);
  const v = await r.json();
  if (!r.ok) throw Error(v.error || "请求未完成");
  return v;
}
function modal(content) {
  $("#modal-content").replaceChildren(content);
  $("#modal").showModal();
}
function closeModal() {
  $("#modal").close();
}
function title(eyebrow, heading, description) {
  const h = node("section", "hero");
  add(
    h,
    node("p", "eyebrow", eyebrow),
    node("h1", "", heading),
    node("p", "", description),
    node("div", "orbit"),
  );
  return h;
}
function panel(heading, index) {
  const p = node("section", "panel"),
    head = node("div", "panel-heading");
  add(head, node("h2", "", heading), node("span", "index", index || ""));
  p.append(head);
  return p;
}
function empty(text) {
  return node("div", "empty", text);
}
function chip(text, warning = false) {
  return node("span", "chip" + (warning ? " warning" : ""), text);
}
function stats() {
  const n = node("div", "stats");
  for (const [v, t] of [
    [state.overview.runs.length, "近期作品"],
    [
      state.overview.runs.filter((x) => x.status === "needs_review").length,
      "等待审核",
    ],
    [state.overview.models.filter((x) => x.available).length, "已启用能力"],
  ])
    add(
      n,
      add(
        node("div", "stat"),
        node("strong", "", String(v)),
        node("span", "", t),
      ),
    );
  return n;
}
async function refresh() {
  state.profile = $("#profile").value.trim() || "default";
  state.overview = await api(
    "/api/overview?profile=" + encodeURIComponent(state.profile),
  );
}
async function navigate(view) {
  state.view = view;
  await refresh();
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("#breadcrumb").textContent =
    "工作空间 / " +
    ({
      create: "创作台",
      runs: "作品档案",
      books: "我的书架",
      timelines: "剪辑台",
      assets: "素材与音乐",
      research: "学习雷达",
      growth: "成长记录",
    }[view] || "作品详情");
  $("#content").classList.toggle("timeline-content", view === "timelines");
  $("#content").replaceChildren();
  if (view === "create") createView();
  if (view === "runs") runsView();
  if (view === "books") booksView();
  if (view === "research") await researchView();
  if (view === "growth") growthView();
  if (view === "timelines") await timelineView();
  if (view === "assets") await mediaView();
}
function workCard(run) {
  const card = node("button", "work-card");
  card.type = "button";
  add(
    card,
    node(
      "div",
      "work-icon",
      { cover: "◒", novel: "✎", bookcast: "▷", podcast: "◉" }[
        run.brief.format
      ] || "▤",
    ),
    node("h3", "", run.brief.topic),
    node("p", "", formats[run.brief.format] || run.brief.format),
    add(
      node("div", "foot"),
      chip(statuses[run.status] || run.status, run.status === "blocked"),
      node("small", "subtle", run.created?.slice(0, 10) || ""),
    ),
  );
  card.onclick = () => openRun(run.id).catch((e) => toast(e.message));
  return card;
}
function recent(parent, all = false) {
  const head = node("div", "section-head");
  add(
    head,
    node("h2", "", all ? "你的作品档案" : "最近创作"),
    !all && button("查看全部 ↗", () => navigate("runs")),
  );
  parent.append(head);
  const runs = state.overview.runs.slice(0, all ? 300 : 3);
  const cards = node("div", "cards");
  for (const r of runs) cards.append(workCard(r));
  parent.append(runs.length ? cards : empty("第一件作品，从一个想法开始。"));
}
function createView() {
  const root = $("#content");
  add(
    root,
    title(
      "YOUR NEXT CREATION",
      "把一个想法，织成作品。",
      "选择一种表达方式，让合适的模型完成合适的步骤。每一个选择，都能被看见。",
    ),
    stats(),
  );
  const grid = node("div", "creation-grid"),
    form = panel("从想法开始", "01 / BRIEF"),
    plan = panel("为你编排创作路径", "02 / PLAN");
  const topic = textarea();
  topic.id = "brief-topic";
  topic.placeholder =
    "例如：一张关于海边阅读时光的封面，安静、简洁，有一点探索的感觉。";
  topic.maxLength = 10000;
  const format = select(Object.entries(formats).filter(([id]) => id !== "research"), "cover"),
    language = select([
      ["zh", "中文"],
      ["en", "English"],
    ]),
    budget = input("1", "number");
  budget.min = "0";
  budget.step = "0.01";
  const local = input("", "checkbox");
  local.checked = true;
  const check = node("label", "check");
  add(check, local, document.createTextNode("仅使用本地模型与工具"));
  const book = select([
      ["", "不使用书籍原文"],
      ...state.overview.books.map((b) => [b.id, b.title]),
    ]),
    units = select([["0", "第 1 段"]]),
    unitField = field("原文段落", units);
  unitField.hidden = true;
  book.onchange = async () => {
    try {
      if (book.value) {
        const b = await api("/api/books/" + book.value);
        units.replaceChildren();
        for (const u of b.units) {
          const o = node("option", "", `${u.index + 1} · ${u.title}`);
          o.value = u.index;
          units.append(o);
        }
        unitField.hidden = false;
      } else unitField.hidden = true;
    } catch (e) {
      toast(e.message);
    }
  };
  add(
    form,
    field("你想创作什么？", topic),
    add(node("div", "row"), field("作品形式", format), field("语言", language)),
    field("预算上限（估计单位）", budget),
    field("原文素材（可选）", book),
    unitField,
    check,
  );
  const hint = add(
    node("div", "empty-plan"),
    add(
      node("div", "diagram"),
      node("i", "", "✎"),
      node("b", "", "—"),
      node("i", "", "✳"),
      node("b", "", "—"),
      node("i", "", "▷"),
    ),
    node("h3", "", "先看看，想法如何成为作品"),
    node("p", "", "预览模型选择、步骤与估计消耗。确认方案后，再开始制作。"),
  );
  plan.append(hint);
  function invalidate() {
    if (state.draft) {
      state.draft = null;
      plan.replaceChildren(
        add(node("div", "panel-heading"), node("h2", "", "创作要求已更新")),
        node("p", "subtle", "请重新预览，确认新的方案后再制作。"),
      );
    }
  }
  for (const control of [topic, format, language, budget, local, book, units]) {
    control.addEventListener("input", invalidate);
    control.addEventListener("change", invalidate);
  }
  const preview = button(
    "预览创作方案  ↗",
    async () => {
      if (!topic.value.trim()) throw Error("先写下你的创作想法。");
      const request = {
        brief: {
          topic: topic.value,
          format: format.value,
          language: language.value,
          profile: state.profile,
          budget: Number(budget.value),
          local_only: local.checked,
          max_latency: 300,
        },
      };
      if (book.value) {
        request.book = book.value;
        request.unit = Number(units.value);
      }
      state.draft = await api("/api/plans", request);
      state.createKey = crypto.randomUUID();
      renderPlan(plan, state.draft.plan);
      const actions = node("div", "form-actions");
      async function save(execute) {
        if (!state.draft) throw Error("请先重新预览方案。");
        const created = await api(
          "/api/runs",
          { draft: state.draft.draft },
          state.createKey,
        );
        if (execute) await startAction(created.run, "execute");
        else await openRun(created.run);
      }
      add(
        actions,
        button("保存计划", () => save(false)),
        button("按此方案制作 ↗", () => save(true), "primary"),
      );
      plan.append(actions);
    },
    "primary",
  );
  add(
    form,
    add(node("div", "form-actions"), preview),
    node(
      "p",
      "mini-note",
      "本地图形封面无需密钥；其他形式使用你已配置的模型。",
    ),
  );
  add(grid, form, plan);
  root.append(grid);
  recent(root);
}
function renderPlan(parent, plan) {
  parent.replaceChildren(
    add(
      node("div", "panel-heading"),
      node("h2", "", "已为你编排的路径"),
      chip(plan.steps.length + " 个步骤"),
    ),
  );
  parent.append(node("p", "subtle", "本方案：" + plan.brief.topic));
  const list = node("div", "step-list");
  for (const [i, s] of plan.steps.entries()) {
    const card = node("div", "step-card");
    add(
      card,
      add(
        node("div", "step-head"),
        node(
          "strong",
          "",
          `${String(i + 1).padStart(2, "0")}  ${stages[s.id] || s.id}`,
        ),
        chip(s.model.local ? "本地" : "云端"),
      ),
      node(
        "p",
        "model-name",
        s.model.adapter === "cover" ? "本地图形排版 · 可编辑 SVG" : s.model.id,
      ),
    );
    const chosen = s.decision.candidates.find(
      (c) => c.model === s.decision.selected,
    );
    const details = node("details"),
      summary = node("summary", "", "为什么选择它？");
    add(
      details,
      summary,
      node(
        "p",
        "",
        `任务 ${s.task || s.id} · 质量估计 ${(chosen?.quality || 0).toFixed(2)} · 已参考 ${chosen?.feedback_count || 0} 次评分。`,
      ),
    );
    for (const c of s.decision.candidates)
      add(details, node("p", "", `${c.model}：综合分 ${c.score.toFixed(3)}`));
    for (const r of s.decision.rejected)
      add(details, node("p", "", `${r.model}：${r.reasons.join("；")}`));
    card.append(details);
    list.append(card);
  }
  add(
    parent,
    list,
    add(
      node("div", "plan-total"),
      node("span", "", "预估消耗"),
      node(
        "strong",
        "",
        `${plan.estimated_cost.toFixed(3)} 单位 · ${Math.ceil(plan.estimated_latency)} 秒`,
      ),
    ),
    node(
      "p",
      "mini-note",
      "依据模型配置与历史表现估计，不是实际账单或时长保证。",
    ),
  );
}
function runsView() {
  add(
    $("#content"),
    title(
      "YOUR CREATIVE ARCHIVE",
      "让每一次创作，都有迹可循。",
      "从方案到产物、从审核到交付，保留每一步的决定与结果。",
    ),
    stats(),
  );
  recent($("#content"), true);
}
async function startAction(run, operation) {
  const action = await api(
    `/api/runs/${run}/${operation}`,
    {},
    crypto.randomUUID(),
  );
  toast(operation === "execute" ? "已开始制作。" : "正在检查并继续任务。");
  await openRun(run);
  watchAction(action.id, run);
}
function watchAction(action, run) {
  if (watchedActions.has(action)) return;
  watchedActions.add(action);
  let attempts = 0;
  async function poll() {
    try {
      const a = await api("/api/actions/" + action);
      if (["queued", "running"].includes(a.status) && attempts++ < 600) {
        setTimeout(poll, 1000);
        return;
      }
      watchedActions.delete(action);
      if (a.error) toast(a.error);
      if (state.view === "detail" && state.run === run) await openRun(run);
    } catch (e) {
      watchedActions.delete(action);
      toast(e.message);
    }
  }
  setTimeout(poll, 750);
}
async function openRun(id) {
  state.view = "detail";
  state.run = id;
  const run = await api("/api/runs/" + id);
  const root = $("#content");
  root.classList.remove("timeline-content");
  root.replaceChildren();
  $("#breadcrumb").textContent = "工作空间 / 作品详情";
  const titleBlock = node("div", "detail-title"),
    heading = node("div");
  add(
    heading,
    node("p", "eyebrow", formats[run.brief.format] || "CREATION"),
    node("h1", "", run.brief.topic),
    chip(statuses[run.status] || run.status, run.status === "blocked"),
  );
  const active = run.actions.find((a) =>
    ["queued", "running"].includes(a.status),
  );
  if (active) watchAction(active.id, id);
  const tools = node("div", "toolbar");
  if (run.status === "ready" && !run.plan.benchmark)
    tools.append(
      button("开始制作 ↗", () => startAction(id, "execute"), "primary"),
    );
  if (!active && ["waiting_external", "executing"].includes(run.status))
    tools.append(button("检查并继续", () => startAction(id, "resume")));
  if (run.status === "needs_review")
    tools.append(
      button(
        "确认审核通过",
        async () => {
          await api(`/api/runs/${id}/approve`, {});
          toast("审核已保存，产物摘要已核验。");
          await openRun(id);
        },
        "primary",
      ),
    );
  if (run.status === "approved") {
    const link = node("a", "download", "下载交付包 ↓");
    link.href = "/api/export/" + id;
    tools.append(link);
  }
  if (run.experiment_lab) tools.append(button("返回配对实验", () => openLab(run.experiment_lab)));
  tools.append(button("刷新", () => openRun(id)));
  add(titleBlock, heading, tools);
  root.append(titleBlock);
  const layout = node("div", "detail-layout"),
    main = node("div", "detail-main"),
    aside = node("div", "detail-aside");
  for (const [i, s] of run.plan.steps.entries()) {
    const saved = run.steps.find((x) => x.id === s.id),
      p = panel(stages[s.id] || s.id, String(i + 1).padStart(2, "0"));
    add(
      p,
      add(
        node("div", "step-head"),
        node("span", "model-name", s.model.id),
        chip(
          saved.status === "done"
            ? "已完成"
            : {
                pending: "等待前序",
                running: "执行中",
                waiting_external: "等待交付",
                uncertain: "需核对结果",
                failed: "未完成",
              }[saved.status] || saved.status,
        ),
      ),
    );
    if (s.editorial_technique) p.append(node("p", "mini-note", "本步骤编辑方法："+s.editorial_technique));
    if (saved.result) {
      const base = `/api/artifacts/${id}/${s.id}/`,
        artifact = node("div", "artifact");
      if (s.capability === "text") {
        const pre = node("pre", "", "正在读取文稿…");
        artifact.append(pre);
        fetch(base + "main")
          .then((r) => {
            if (!r.ok) throw Error();
            return r.text();
          })
          .then((t) => (pre.textContent = t))
          .catch(() => (pre.textContent = "产物缺失或发生变化，请检查任务。"));
      } else if (s.capability === "image") {
        let slot = "main";
        const svg = saved.result.supplements.findIndex((x) =>
          x.file.endsWith(".svg"),
        );
        if (svg >= 0) slot = "s" + svg;
        const img = node("img");
        img.alt = "作品封面预览";
        img.src = base + slot;
        artifact.append(img);
      } else {
        const media = node(s.capability === "audio" ? "audio" : "video");
        media.controls = true;
        media.preload = "metadata";
        media.src = base + "main";
        artifact.append(media);
      }
      const links = node("div", "artifact-links");
      const a = node("a", "", "打开产物 ↗");
      a.href = base + "main";
      a.target = "_blank";
      a.rel = "noreferrer";
      links.append(a);
      add(p, artifact, links);
      if (["needs_review", "approved"].includes(run.status) && !run.plan.benchmark) {
        const rating = node("div", "feedback");
        rating.append(node("span", "subtle", "这一步的效果："));
        for (let value = 1; value <= 5; value++)
          rating.append(
            button(String(value) + "分", async () => {
              await api(`/api/runs/${id}/feedback`, {
                step: s.id,
                rating: value / 5,
              });
              toast("评分已保存，将用于后续同类任务的选择。");
            }),
          );
        p.append(rating);
      }
    }
    main.append(p);
  }
  const summary = panel("这次创作的决定");
  add(
    summary,
    add(
      node("div", "metric"),
      node("span", "", "预算估计"),
      node("strong", "", run.plan.estimated_cost.toFixed(3) + " 单位"),
    ),
    add(
      node("div", "metric"),
      node("span", "", "隐私偏好"),
      node("strong", "", run.brief.local_only ? "仅本地" : "允许云端"),
    ),
    node("p", "mini-note", "审核只保存本地确认，不会向社交平台发布。"),
  );
  if (["needs_review", "approved"].includes(run.status))
    summary.append(button("创作复盘与练习 ↗", () => coachDialog(run), "wide"));
  if (["waiting_external", "blocked", "executing"].includes(run.status))
    summary.append(button("查看远端任务", () => remoteDialog(run), "wide"));
  aside.append(summary);
  if (run.plan.context?.series && run.status === "approved") {
    const current = await api("/api/series/" + run.plan.context.series.id);
    if (
      current.pending_run === run.id &&
      current.version === run.plan.context.series.version
    )
      aside.append(seriesAcceptPanel(run));
    else
      aside.append(
        node("p", "note-box", "此集的系列状态已更新，请在书架查看当前进度。"),
      );
  }
  const events = panel("过程记录");
  for (const e of run.events.slice(0, 8))
    add(
      events,
      add(
        node("div", "event"),
        node(
          "b",
          "",
          {
            created: "创作方案已保存",
            started: "开始制作",
            approved: "作品审核通过",
            waiting_external: "等待外部任务",
            remote_reconciled: "已绑定核对后的任务",
            feedback: "创作评分已更新",
          }[e.kind] || e.kind,
        ),
        node("span", "", e.created),
      ),
    );
  aside.append(events);
  add(layout, main, aside);
  root.append(layout);
}
function seriesAcceptPanel(run) {
  const p = panel("接续下一集"),
    notes = textarea(run.plan.context.continuity);
  add(
    p,
    field("本集确认的事实与后续线索", notes),
    button(
      "保存连续性笔记并推进",
      async () => {
        const series = run.plan.context.series;
        await api(`/api/series/${series.id}/accept`, {
          run: run.id,
          version: series.version,
          continuity: notes.value,
        });
        toast("本集已接受，可在书架规划下一集。");
        await navigate("books");
      },
      "primary wide",
    ),
  );
  return p;
}
async function remoteDialog(run) {
  const batches = await api("/api/remote/" + run.id),
    box = node("div");
  box.append(node("h2", "", "远端任务记录"));
  if (!batches.length)
    box.append(
      empty("没有已记录的异步任务。同步调用结果不明时，请先在提供方核对。"),
    );
  for (const batch of batches)
    for (const segment of batch.segments) {
      const card = node("div", "research-card");
      add(
        card,
        chip(`第 ${segment.index + 1} 段 · ${segment.status}`),
        node("p", "", segment.text),
        node("p", "model-name", segment.job_id || "尚未获得可信任务号"),
      );
      if (["unknown", "submitting"].includes(segment.status)) {
        const job = input();
        add(
          card,
          field("已在 MediaFlow 核对的任务号", job),
          button(
            "核验并绑定已有任务",
            async () => {
              await api(`/api/runs/${run.id}/reconcile`, {
                step: batch.step,
                segment: segment.index,
                job: job.value.trim(),
              });
              closeModal();
              toast("已有任务已绑定，没有提交新的推理。");
              await openRun(run.id);
            },
            "primary",
          ),
        );
      }
      box.append(card);
    }
  modal(box);
}
async function coachDialog(run) {
  const workbook = await api(`/api/runs/${run.id}/coach`, {}),
    box = node("div");
  add(
    box,
    node("p", "eyebrow", "REFLECT & IMPROVE"),
    node("h2", "", "把这次创作，变成一次练习"),
    node(
      "p",
      "subtle",
      "选择一个维度，做一次明确的修改，并解释你的判断。评分属于自评，不代表已验证的能力提升。",
    ),
  );
  for (const stage of workbook.stages) {
    const p = node("div", "research-card");
    p.append(node("h3", "", stages[stage.step] || stage.step));
    for (const [d, q] of Object.entries(stage.rubric))
      p.append(
        node("p", "", `${dimensions[d] || d}：${reviewQuestions[d] || q}`),
      );
    if (stage.capability === "text") {
      const revision = textarea(),
        dimension = select(
          Object.keys(stage.rubric).map((d) => [d, dimensions[d] || d]),
        ),
        before = input("0.5", "number"),
        after = input("0.7", "number"),
        reason = textarea();
      const original = await fetch(
        `/api/artifacts/${run.id}/${stage.step}/main`,
      );
      if (original.ok) revision.value = await original.text();
      for (const n of [before, after]) {
        n.min = 0;
        n.max = 1;
        n.step = 0.1;
      }
      add(
        p,
        field("选择练习维度", dimension),
        field("修改后的文稿", revision),
        add(
          node("div", "row"),
          field("原稿自评（0–1）", before),
          field("修改后自评（0–1）", after),
        ),
        field("具体改了什么，为什么更好？", reason),
        button(
          "保存这次练习",
          async () => {
            await api(`/api/runs/${run.id}/practice`, {
              step: stage.step,
              revision: revision.value,
              dimension: dimension.value,
              before: Number(before.value),
              after: Number(after.value),
              rationale: reason.value,
            });
            toast("修改稿与评分理由已保存。");
            closeModal();
          },
          "primary",
        ),
      );
    }
    box.append(p);
  }
  modal(box);
}
function booksView() {
  const root = $("#content");
  add(
    root,
    title(
      "YOUR SOURCE LIBRARY",
      "长故事，从这里接续。",
      "导入有权使用的文本，检查分段，再逐集创作与审核。",
    ),
  );
  const head = node("div", "section-head");
  add(
    head,
    node("h2", "", "原文书架"),
    button("＋ 导入书籍", importBookDialog, "primary"),
  );
  root.append(head);
  const cards = node("div", "cards");
  for (const book of state.overview.books) {
    const card = node("div", "work-card");
    add(
      card,
      node("div", "work-icon", "▥"),
      node("h3", "", book.title),
      node("p", "", `${book.units} 个原文单元 · ${book.format.toUpperCase()}`),
      button("查看原文单元", () => bookPreview(book)),
      button("规划连续作品 ↗", () => seriesDialog(book)),
    );
    cards.append(card);
  }
  root.append(
    state.overview.books.length
      ? cards
      : empty("支持 TXT 与未加密 EPUB。原文件只保存在本机数据目录。"),
  );
  root.append(add(node("div", "section-head"), node("h2", "", "连续作品")));
  for (const series of state.overview.series) {
    const p = node("div", "research-card");
    add(
      p,
      node("h3", "", series.definition.brief.topic),
      node(
        "p",
        "",
        series.completed
          ? `已完成全部 ${series.unit_count} 个原文单元`
          : `待创作原文单元 ${series.cursor + 1} · 版本 ${series.version}`,
      ),
      button(series.pending_run ? "打开当前集" : "规划下一集", async () => {
        if (series.pending_run) return openRun(series.pending_run);
        const next = await api(`/api/series/${series.id}/next`, {});
        await openRun(next.run);
      }),
    );
    if (series.completed) p.querySelector("button")?.remove();
    root.append(p);
  }
  if (!state.overview.series.length)
    root.append(empty("从书架选择一本书，开始逐集创作。"));
}
async function bookPreview(book) {
  const b = await api("/api/books/" + book.id),
    box = node("div"),
    unit = select(
      b.units.map((u) => [String(u.index), `${u.index + 1} · ${u.title}`]),
    ),
    text = node("pre");
  const area = node("div", "artifact");
  area.append(text);
  add(box, node("h2", "", book.title), field("检查原文段落", unit), area);
  async function load() {
    const c = await api(`/api/books/${book.id}?unit=${unit.value}`);
    text.textContent = c.source.text;
  }
  unit.onchange = () => load().catch((e) => toast(e.message));
  await load();
  modal(box);
}
function importBookDialog() {
  const box = node("div"),
    titleInput = input(),
    file = input("", "file"),
    rights = select([
      ["", "请选择使用权"],
      ["owned", "我创作的文本"],
      ["licensed", "已获得授权"],
      ["public-domain", "公版作品"],
    ]);
  file.accept = ".txt,.epub";
  add(
    box,
    node("h2", "", "导入原文"),
    field("书籍标题", titleInput),
    field("TXT / EPUB 文件（最多 8 MB）", file),
    field("使用权声明", rights),
    node("p", "subtle", "仅导入你有权使用的文本。请检查导入后的章节划分。"),
    button(
      "导入到本机书架",
      async () => {
        const f = file.files[0];
        if (
          !f ||
          f.size > 8 * 1024 * 1024 ||
          !titleInput.value.trim() ||
          !rights.value
        )
          throw Error("请填写标题、选择文件和使用权。");
        const encoded = await new Promise((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(r.result.split(",")[1]);
          r.onerror = reject;
          r.readAsDataURL(f);
        });
        await api("/api/books", {
          title: titleInput.value,
          format: f.name.split(".").pop().toLowerCase(),
          rights: rights.value,
          data: encoded,
        });
        closeModal();
        await navigate("books");
        toast("原文已导入，请检查分段。 ");
      },
      "primary wide",
    ),
  );
  modal(box);
}
async function seriesDialog(book) {
  const metadata = await api("/api/books/" + book.id),
    box = node("div"),
    topic = textarea("保留人物与事件顺序，改编为清晰的中文叙事。"),
    format = select([
      ["novel", "小说改编"],
      ["article", "章节文章"],
      ["podcast", "播客口播"],
      ["bookcast", "有声故事视频"],
      ["talkshow", "单口节目"],
    ]),
    start = select(
      metadata.units.map((u) => [
        String(u.index),
        `${u.index + 1} · ${u.title}`,
      ]),
    ),
    notes = textarea();
  add(
    box,
    node("h2", "", book.title + " · 新建连续作品"),
    field("改编要求", topic),
    field("作品形式", format),
    field("从哪一段开始", start),
    field("初始人物与连续性笔记（可选）", notes),
    button(
      "保存系列",
      async () => {
        await api("/api/series", {
          book: book.id,
          start_unit: Number(start.value),
          continuity: notes.value,
          brief: {
            topic: topic.value,
            format: format.value,
            profile: state.profile,
            language: "zh",
            budget: 1,
            local_only: true,
            max_latency: 300,
          },
        });
        closeModal();
        await navigate("books");
      },
      "primary wide",
    ),
  );
  modal(box);
}
async function researchView() {
  const root = $("#content"),
    data = await api("/api/research?profile="+encodeURIComponent(state.profile));
  add(
    root,
    title(
      "LEARN WITH EVIDENCE",
      "让新的可能，成为可验证的改进。",
      "保留来源与修订记录；新资料经过评审和实验后，才影响未来创作。",
    ),
  );
  const labs = panel("模型辅助研究与实验"), labCards = node("div", "cards");
  for (const lab of data.labs) {
    const card = button("", () => openLab(lab.id), "work-card");
    add(card, node("h3", "", lab.protocol.goal), node("p", "", lab.protocol.task), chip(lab.technique_state === "active" ? "当前方法根" : lab.evaluation ? "已有留出集评估" : lab.accepted ? "已审核提案" : statuses[lab.run_status] || lab.run_status));
    labCards.append(card);
  }
  labs.append(data.labs.length ? labCards : empty("从下面一条公开资料选择「模型辅助整理」。模型建议仍需引用核对、许可/兼容性评审和独立留出集实验。"));
  root.append(labs);
  const sources = panel("已订阅的公开来源");
  for (const source of data.sources)
    add(
      sources,
      add(
        node("div", "source-row"),
        node("strong", "", source.id),
        node("span", "subtle", source.enabled ? "已启用" : "已停用"),
      ),
    );
  if (!data.sources.length)
    sources.append(
      empty(
        "还没有订阅。可通过终端 source-add 添加 GitHub、Hugging Face 或 arXiv 公开订阅。",
      ),
    );
  root.append(sources);
  root.append(add(node("div", "section-head"), node("h2", "", "研究收件箱")));
  for (const item of data.items) {
    const p = node("div", "research-card");
    add(
      p,
      chip(
        item.review_stale
          ? "资料更新 · 需复核"
          : { inbox: "待评审", proposed: "已创建提案", dismissed: "已忽略" }[
              item.state
            ] || item.state,
        item.review_stale,
      ),
      node("h3", "", item.payload.title),
      node("p", "", item.payload.summary.slice(0, 700)),
      node(
        "p",
        "subtle",
        "命中词：" + (item.matched_keywords.join("、") || "无"),
      ),
    );
    const link = node("a", "subtle", "查看公开来源 ↗");
    link.href = item.payload.source;
    link.target = "_blank";
    link.rel = "noreferrer";
    p.append(link);
    if (item.state !== "dismissed")
      p.append(
        add(
          node("div", "toolbar"),
          button("整理为实验提案", () => proposalDialog(item)),
          button("模型辅助整理", () => labDialog(item, data.items, data.tasks)),
        ),
      );
    root.append(p);
  }
  if (!data.items.length)
    root.append(
      empty(
        "资料被收集后会出现在这里。关键词命中只是相关性线索，不是质量判断。",
      ),
    );
}
function proposalDialog(item) {
  const box = node("div"),
    name = input(),
    guidance = textarea(),
    note = textarea();
  add(
    box,
    node("h2", "", "从证据到实验"),
    node("p", "subtle", item.payload.title),
    field("实验标识（字母、数字、短横线）", name),
    field("可验证的具体编辑方法", guidance),
    field("阅读了什么，为什么适合当前任务？", note),
    button(
      "保存为待评测提案",
      async () => {
        await api("/api/research/propose", {
          item: item.id,
          revision: item.revision,
          technique: name.value,
          guidance: guidance.value,
          note: note.value,
        });
        closeModal();
        toast("提案已保存，尚未启用。请按配对评测流程验证。 ");
        await navigate("research");
      },
      "primary wide",
    ),
  );
  modal(box);
}
function growthView() {
  const root = $("#content"),
    progress = state.overview.progress;
  add(
    root,
    title(
      "YOUR CREATIVE PRACTICE",
      "让作品变好，也让判断更清晰。",
      "每次只打磨一个维度。保存修改、比较原稿，并说清楚为什么。",
    ),
  );
  const cards = node("div", "cards");
  for (const d of progress.dimensions) {
    const p = node("div", "work-card");
    add(
      p,
      node("div", "work-icon", "↗"),
      node("h3", "", dimensions[d.dimension] || d.dimension),
      node("p", "", `${d.attempts} 次练习`),
      node(
        "strong",
        "",
        `平均自评变化 ${d.mean_self_reported_delta >= 0 ? "+" : ""}${d.mean_self_reported_delta.toFixed(2)}`,
      ),
    );
    cards.append(p);
  }
  root.append(
    progress.dimensions.length
      ? cards
      : empty("从任意已完成作品打开「创作复盘与练习」，保存第一份修改稿。"),
  );
  root.append(
    node(
      "p",
      "mini-note",
      "这里展示人工自评记录，不代表经独立验证的技能提升。",
    ),
  );
  recent(root);
}
async function connect(code) {
  await api("/api/session", { code });
  $("#login").hidden = true;
  $("#workspace").hidden = false;
  await navigate("create");
}
$("#login-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await connect($("#access-code").value);
    $("#access-code").value = "";
  } catch (e) {
    $("#login-error").textContent = e.message;
  }
};
$("#close-modal").onclick = closeModal;
$(".brand").onclick = (e) => {
  e.preventDefault();
  navigate("create").catch((error) => toast(error.message));
};
$("#refresh").onclick = () =>
  state.view === "detail"
    ? openRun(state.run).catch((e) => toast(e.message))
    : state.view === "lab-detail"
      ? openLab(labUI.id).catch(e => toast(e.message))
    : state.view === "music-detail"
      ? openMusic(mediaUI.project).catch(e => toast(e.message))
    : state.view === "timeline-detail"
      ? (timelineUI.loaded ? openTimeline(timelineUI.loaded.id, timelineUI.loaded.version) : navigate("timelines")).catch(e => toast(e.message))
      : state.view === "timeline-edit"
        ? renderTimelineEditor()
        : navigate(state.view).catch((e) => toast(e.message));
$("#profile").onchange = () =>
  navigate(state.view === "detail" ? "runs" : state.view.startsWith("timeline") ? "timelines" : state.view === "music-detail" ? "assets" : state.view === "lab-detail" ? "research" : state.view).catch((e) =>
    toast(e.message),
  );
document
  .querySelectorAll("nav button")
  .forEach(
    (b) =>
      (b.onclick = () =>
        navigate(b.dataset.view).catch((e) => toast(e.message))),
  );
(async () => {
  const code = location.hash.slice(1);
  history.replaceState(null, "", location.pathname);
  try {
    if (code) await connect(code);
    else {
      await api("/api/session");
      $("#workspace").hidden = false;
      await navigate("create");
    }
  } catch (e) {
    $("#login").hidden = false;
    $("#workspace").hidden = true;
  }
})();
