"use strict";
const labUI = { id: null, request: 0, watched: new Set(), reviews: new Map() };
function labDialog(selected, items, tasks) {
  const box = node("div", "media-form"), form = node("form"), choices = items.filter(i => i.state !== "dismissed"), checks = new Map();
  const target = select(tasks.map(task => { const [fmt, step] = task.split(":"); return [task, `${formats[fmt] || fmt} · ${stages[step] || step}`]; })), goal = textarea("基于所选公开摘要，为当前任务提出可检验的编辑方法，保留原始引用，并说明证据和许可的限制。"), budget = timelineNumber(1, 0, 100000, 0.01), local = mediaCheck("仅使用本地文字模型", true);
  goal.required = true; goal.minLength = 10; goal.maxLength = 1500;
  add(box, node("h2", "", "从公开证据到可检验提案"), node("p", "mini-note", "仅发送所选版本的标题、摘要与研究目标，不自动读取全文或执行来源中的指令。先保存模型计划，再由你明确开始制作。"), form);
  for (const item of choices) { const check = mediaCheck(item.payload.title+" · 版本 "+item.revision, item.id === selected.id); checks.set(item.id, check.checkbox); form.append(check.label); }
  add(form, node("p", "mini-note", "选择 1–4 条资料。摘要越长，对模型输入容量的要求越高。"), field("希望改进的具体任务", target), field("研究目标", goal), field("综合阶段预算（配置估计单位）", budget), local.label);
  const submit = node("button", "primary", "保存证据与综合计划"); submit.type = "submit"; form.append(submit);
  const id = "lab-"+crypto.randomUUID(); let key = crypto.randomUUID(); form.addEventListener("input", () => key = crypto.randomUUID()); form.addEventListener("change", () => key = crypto.randomUUID());
  form.onsubmit = async event => {
    event.preventDefault(); if (!form.reportValidity()) return;
    const sources = choices.filter(i => checks.get(i.id).checked).map(i => ({ item: i.id, revision: i.revision }));
    if (!sources.length || sources.length > 4) return toast("请选择 1–4 条资料。");
    const restore = mediaFreeze(form);
    try { const lab = await api("/api/labs", { id, spec: { task: target.value, sources, goal: goal.value, budget: Number(budget.value), local_only: local.checkbox.checked, profile: state.profile, language: "zh" } }, key); if (mediaCurrent(box)) { closeModal(); await openLab(lab.id); } }
    catch (error) { toast(error.message); } finally { restore(); }
  };
  modal(box);
}
function watchLabAction(action, name) {
  if (labUI.watched.has(action)) return; labUI.watched.add(action); let count = 0;
  async function poll() {
    try { const value = await api("/api/actions/"+action); if (["queued", "running"].includes(value.status) && count++ < 900) { setTimeout(poll, 1500); return; } labUI.watched.delete(action); if (value.error) toast(value.error); if (state.view === "lab-detail" && labUI.id === name) await openLab(name); }
    catch (error) { labUI.watched.delete(action); toast(error.message); }
  }
  setTimeout(poll, 1000);
}
async function labOutput(name, caseId, label, capability, parent) {
  const path = `/api/labs/${name}/cases/${caseId}/${label}`;
  if (capability === "text") {
    const pre = node("pre", "", "正在核验产物…"); parent.append(pre);
    try { const response = await fetch(path); if (!response.ok) throw Error(); pre.textContent = await response.text(); }
    catch { pre.textContent = "产物缺失、发生变化或尚未开放。"; }
  } else {
    const preview = node(capability === "image" ? "img" : capability === "audio" ? "audio" : "video");
    if (capability === "image") preview.alt = "盲评产物 "+label;
    else { preview.controls = true; preview.preload = "metadata"; }
    preview.src = path; parent.append(preview);
  }
}
async function openLab(name) {
  state.view = "lab-detail"; labUI.id = name;
  const request = ++labUI.request, lab = await api("/api/labs/"+name);
  if (state.view !== "lab-detail" || request !== labUI.request) return;
  const root = $("#content"); root.classList.add("timeline-content"); root.replaceChildren(); $("#breadcrumb").textContent = "工作空间 / 学习雷达 / 研究实验";
  const heading = node("div", "detail-title"); add(heading, add(node("div"), node("p", "eyebrow", "EVIDENCE · PROPOSAL · HOLDOUT"), node("h1", "", "让一个方法，经得起比较。"), node("p", "subtle", lab.protocol.goal)), add(node("div", "toolbar"), button("返回学习雷达", () => navigate("research")), button("查看综合计划与产物", () => openRun(lab.run_id)), button("刷新", () => openLab(name)))); root.append(heading);
  const sources = panel("冻结的公开证据");
  for (const source of lab.protocol.sources) { const link = node("a", "", source.snapshot.title); link.href = source.snapshot.source; link.target = "_blank"; link.rel = "noreferrer"; add(sources, link, node("p", "mini-note", `版本 ${source.revision} · 仅标题与摘要，未代表全文阅读`), node("p", "", source.snapshot.summary)); }
  if (!lab.accepted && (lab.evidence_stale || lab.baseline_stale)) sources.append(node("p", "mini-note", "所选资料或当前方法基线已有变化。该版本可留存查看，但需新建研究后才能接受提案。")); root.append(sources);
  const proposal = panel("模型建议与人工核对");
  if (!["needs_review", "approved"].includes(lab.run_status)) proposal.append(empty("先查看冻结计划，并明确执行综合任务。已有运行不会因刷新而重新提交。"));
  else {
    let draft;
    try { draft = await api(`/api/labs/${name}/draft`); } catch (error) { proposal.append(node("p", "mini-note", "输出不符合结构或引用要求，不能转成提案。可查看原始产物；系统不会自动重做。")); }
    if (state.view !== "lab-detail" || request !== labUI.request) return;
    if (draft?.status === "insufficient") add(proposal, chip("证据不足 · 不创建方法"), node("p", "", draft.reason));
    else if (draft) {
      add(proposal, node("h3", "", draft.title), node("p", "", draft.hypothesis), node("p", "subtle", "待验证的编辑指令："+draft.guidance));
      for (const citation of draft.citations) add(proposal, node("blockquote", "lab-quote", citation.quote), node("p", "mini-note", "模型解释："+citation.supports));
      add(proposal, node("p", "mini-note", "模型许可提示（不是许可结论）："+draft.license_caution), node("p", "mini-note", "限制："+draft.limitations));
      const topics = node("ol"); draft.cases.forEach(topic => topics.append(node("li", "", topic))); add(proposal, node("h3", "", "建议的原创测试题"), topics);
      if (lab.run_status === "needs_review") proposal.append(button("确认已核对综合产物", async () => { await api(`/api/runs/${lab.run_id}/approve`, {}); await openLab(name); }));
      if (!lab.accepted && lab.run_status === "approved" && !lab.evidence_stale && !lab.baseline_stale) {
        const form = node("form", "lab-review"), technique = input(), note = textarea(), license = textarea(), compatibility = textarea(), allowed = mediaCheck("我已核对测试题，确认它们为原创或已授权，且适用于本次实验");
        technique.required = true; technique.pattern = "[a-zA-Z0-9_-]{1,64}"; note.required = license.required = compatibility.required = true; note.minLength = license.minLength = compatibility.minLength = 10; note.maxLength = license.maxLength = compatibility.maxLength = 2000; allowed.checkbox.required = true;
        add(form, field("方法标识（字母、数字或短横线）", technique), field("引用与推断核对（至少 10 字）", note), field("许可、引用和素材使用检查（至少 10 字）", license), field("兼容性检查：确认仅为编辑方法（至少 10 字）", compatibility), allowed.label);
        const submit = node("button", "primary", "接受为待实验方法"); submit.type = "submit"; form.append(submit);
        form.onsubmit = async event => { event.preventDefault(); if (!form.reportValidity()) return; const restore = mediaFreeze(form); try { await api(`/api/labs/${name}/accept`, { technique: technique.value, review: { note: note.value, license_review: license.value, compatibility_review: compatibility.value, cases_authorized: allowed.checkbox.checked } }); await openLab(name); } catch (error) { toast(error.message); } finally { restore(); } }; proposal.append(form);
      }
    }
  }
  root.append(proposal);
  if (lab.accepted && !lab.experiment) {
    const plan = panel("预先规划配对实验"), budget = timelineNumber(1, 0, 100000, 0.01), local = mediaCheck("仅使用本地模型", true);
    add(plan, node("p", "mini-note", "创建前冻结所有题目、同对模型、随机 A/B 呈现与开发/留出划分。候选复用同一上游素材；预算是整项实验的配置估计，不是账单上限。"), field("整项实验预算（配置估计单位）", budget), local.label, button("冻结实验计划", async () => { await api(`/api/labs/${name}/experiment`, { settings: { total_budget: Number(budget.value), local_only: local.checkbox.checked, max_latency: 300 } }); await openLab(name); }, "primary")); root.append(plan);
  }
  if (lab.experiment) {
    const trial = lab.experiment, overview = panel("盲评实验与留出验证");
    add(overview, node("p", "", `任务 ${trial.protocol.task} · 配置费用估计 ${trial.protocol.planned_cost_estimate.toFixed(4)}`), node("p", "mini-note", "开发集评分封存后才开放留出集。A/B 隐藏仅作用于评审展示，本机所有者仍能查看映射；相似内容、评分依赖和小样本都会限制结论。"));
    if (trial.state === "development") { const seal = button("封存开发集并开放留出集", async () => { await api(`/api/labs/${name}/seal`, {}); await openLab(name); }); seal.disabled = trial.cases.some(c => c.partition === "development" && !c.reviewed); overview.append(seal); } root.append(overview);
    for (const entry of trial.cases) {
      const p = panel(`${entry.id} · ${entry.partition === "development" ? "开发集" : "留出集"}`), locked = entry.partition === "holdout" && trial.state === "development", base = `/api/labs/${name}/cases/${entry.id}`, done = ["needs_review", "approved"], ready = done.includes(entry.baseline_status) && done.includes(entry.candidate_status);
      if (locked) p.append(empty("留出集尚未开放。请先完成并封存开发集盲评。"));
      else {
        const tools = node("div", "toolbar");
        for (const [arm, text] of [["baseline", "制作控制组"], ["candidate", "制作候选组"]]) {
          const status = entry[arm+"_status"], active = entry.actions.find(a => a.run_id === entry[arm+"_run"]);
          if (active) { tools.append(chip(text+" · 已排队或制作中")); watchLabAction(active.id, name); }
          else if (status === "ready") { const create = button(text, async () => { const action = await api(base+"/"+arm, {}, crypto.randomUUID()); watchLabAction(action.id, name); toast("制作已排队；不会自动重试未知推理。"); await openLab(name); }); if (arm === "candidate" && !done.includes(entry.baseline_status)) create.disabled = true; tools.append(create); }
          else tools.append(button(text.replace("制作", "查看")+" · "+(statuses[status] || status), () => openRun(entry[arm+"_run"])));
        }
        p.append(tools);
        if (ready) {
          const pair = node("div", "lab-pair"); for (const label of ["A", "B"]) { const column = node("section", "timeline-preview"), heading = node("h3", "", label); column.append(heading); pair.append(column); labOutput(name, entry.id, label, lab.target_capability, column); } p.append(pair);
          const link = node("a", "download", "下载 A/B 评审包"); link.href = base+"/packet"; p.append(link);
          if (!entry.reviewed) {
            const key = name+"/"+entry.id, previous = labUI.reviews.get(key) || { A: "", B: "", rationale: "" }; labUI.reviews.set(key, previous);
            const form = node("form", "lab-review"), a = timelineNumber(previous.A, 0, 1, 0.05), b = timelineNumber(previous.B, 0, 1, 0.05), rationale = textarea(previous.rationale); rationale.required = true; rationale.minLength = 10; rationale.maxLength = 4000; a.oninput = () => previous.A = a.value; b.oninput = () => previous.B = b.value; rationale.oninput = () => previous.rationale = rationale.value;
            add(form, add(node("div", "field-grid"), field("A 评分（0–1）", a), field("B 评分（0–1）", b)), field("比较理由（至少 10 字，提交后不可修改）", rationale)); const submit = node("button", "primary", "保存盲评"); submit.type = "submit"; form.append(submit);
            form.onsubmit = async event => { event.preventDefault(); if (!form.reportValidity()) return; const restore = mediaFreeze(form); try { await api(base+"/review", { scores: { A: Number(a.value), B: Number(b.value) }, rationale: rationale.value }); labUI.reviews.delete(key); await openLab(name); } catch (error) { toast(error.message); } finally { restore(); } }; p.append(form);
          } else p.append(chip("盲评已封存"));
          if (entry.baseline_status !== "approved" || entry.candidate_status !== "approved") p.append(button("确认已检查两份实际产物，均审核通过", async () => { await api(base+"/approve", {}); await openLab(name); }));
        }
      }
      root.append(p);
    }
    const finish = panel("留出集结果与显式采用");
    if (!lab.evaluation) { const evaluate = button("评估已审核的留出集", async () => { await api(`/api/labs/${name}/evaluate`, {}); await openLab(name); }, "primary"); evaluate.disabled = trial.cases.some(c => !c.reviewed || c.partition === "holdout" && (c.baseline_status !== "approved" || c.candidate_status !== "approved")); finish.append(evaluate); }
    else { add(finish, chip(lab.evaluation.passed ? "留出集流程门槛通过" : "未通过采用门槛", !lab.evaluation.passed), node("p", "", `平均评分差 ${lab.evaluation.mean_delta.toFixed(3)} · 最差差值 ${lab.evaluation.worst_delta.toFixed(3)}`), node("p", "mini-note", "这是人工评分的小样本结果，不证明独立评审、普遍质量提升或创作者技能收益。开发集评分未参与采用门槛，也未进入模型路由反馈。"));
      if (lab.evaluation.passed && lab.technique_state === "evaluated") finish.append(button("显式启用此任务的方法", async () => { await api(`/api/labs/${name}/promote`, {}); await openLab(name); }, "primary"));
      if (lab.technique_state === "active") finish.append(button("回滚到之前的方法根", async () => { await api(`/api/labs/${name}/rollback`, {}); await openLab(name); }));
    }
    root.append(finish);
  }
}
