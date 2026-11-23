"use strict";
const factKinds = { identity: "身份", appearance: "外观", relationship: "关系", state: "当前状态", constraint: "创作约束" };
async function storyMemoryDialog(seriesId, version) {
  const state = await api(`/api/series/${seriesId}/memory`+(version === undefined ? "" : "?version="+version)), box = node("div", "media-form"), snapshot = state.snapshot;
  add(box, node("h2", "", "角色记忆与事实版本"), node("p", "mini-note", `当前系列版本 ${state.series_version} · 正在查看记忆版本 ${snapshot.version} · 每条事实需保留可核验的引用，由人检查是否合理。`));
  const versions = select([["0", "初始空记忆"], ...state.history.map(item => [String(item.version), "记忆版本 "+item.version+" · "+item.created.slice(0, 10)])], String(snapshot.version));
  versions.onchange = () => storyMemoryDialog(seriesId, Number(versions.value)).catch(e => toast(e.message)); box.append(field("查看历史快照", versions));
  for (const character of snapshot.payload.characters) {
    const card = node("section", "research-card"); card.append(node("h3", "", character.name));
    for (const fact of character.facts) add(card, node("p", "", (factKinds[fact.kind] || fact.kind)+"："+fact.text), node("blockquote", "lab-quote", fact.citation.quote), node("p", "mini-note", fact.citation.kind === "source" ? "原文单元 "+(fact.citation.unit+1) : "本系列已接受章节 · "+(stages[fact.citation.step] || fact.citation.step)));
    box.append(card);
  }
  if (!snapshot.payload.characters.length) box.append(empty("这个版本还没有角色事实。连续性笔记仍独立保留，不会自动变成结构化事实。"));
  const review = state.history.find(item => item.version === snapshot.version); if (review) box.append(node("p", "mini-note", "该版本人工审核说明："+review.review_note));
  if (state.pending_run) add(box, node("p", "mini-note", "已有待完成章节，角色记忆编辑已锁定。请完成或明确拒绝该章后再修改。"), button("打开当前章节", async () => { closeModal(); await openRun(state.pending_run); }));
  else box.append(button(snapshot.version === state.current_version ? "编辑并审核新版本" : "基于此快照恢复为新版本", () => editStoryMemory(seriesId, state), "primary"));
  modal(box);
}
function editStoryMemory(seriesId, memoryState) {
  const draft = JSON.parse(JSON.stringify(memoryState.snapshot.payload)), options = memoryState.evidence_options, originalVersion = memoryState.current_version;
  let reviewNote = "", confirmed = false;
  function render() {
    const box = node("div", "media-form"), form = node("form");
    add(box, node("h2", "", "审核角色事实的新版本"), node("p", "mini-note", "只录入当前原文或已接受章节支持的事实。引用存在不代表推断正确；请检查人物指代、矛盾和时间范围。保存将产生新版本，旧章节的快照不会改变。"), form);
    for (const [characterIndex, character] of draft.characters.entries()) {
      const card = node("section", "research-card"), name = input(character.name); name.required = true; name.maxLength = 100; name.oninput = () => character.name = name.value;
      add(card, field("角色名称", name), button("移除此角色（旧版保留）", () => { draft.characters.splice(characterIndex, 1); render(); }));
      for (const [factIndex, fact] of character.facts.entries()) {
        const row = node("section", "memory-fact"), kind = select(Object.entries(factKinds), fact.kind), text = textarea(fact.text), quote = textarea(fact.citation?.quote || ""), evidence = select([["", "请选择引用来源"], ...options.map((option, index) => [String(index), option.kind === "source" ? `原文单元 ${option.unit+1} · ${option.title}` : option.title])]);
        const ref = fact.citation ? Object.fromEntries(Object.entries(fact.citation).filter(([key]) => !["quote", "sha256"].includes(key))) : null;
        const selected = ref ? options.findIndex(option => Object.keys(ref).every(key => ref[key] === option[key])) : -1; evidence.value = selected < 0 ? "" : String(selected); evidence.required = true;
        kind.onchange = () => fact.kind = kind.value; text.required = true; text.maxLength = 500; text.oninput = () => fact.text = text.value; quote.required = true; quote.minLength = 5; quote.maxLength = 400; quote.oninput = () => { if (fact.citation) fact.citation.quote = quote.value; };
        evidence.onchange = () => { const selected = options[Number(evidence.value)]; if (evidence.value === "" || !selected) { fact.citation = null; return; } const { title, ...citation } = selected; fact.citation = { ...citation, quote: "" }; quote.value = ""; };
        add(row, field("事实类型", kind), field("要保留的事实（最多 500 字）", text), field("证据来源", evidence), button("查看所选证据原文", async () => {
          if (!fact.citation) throw Error("请先选择一个来源。"); const { quote, sha256, ...reference } = fact.citation; const result = await api(`/api/series/${seriesId}/memory/evidence`, { reference });
          const pre = row.querySelector("pre") || node("pre", "memory-source"); pre.textContent = result.text; row.append(pre);
        }), field("逐字引用（5–400 字）", quote), button("移除此事实", () => { character.facts.splice(factIndex, 1); render(); })); card.append(row);
      }
      card.append(button("添加事实", () => { if (character.facts.length >= 20) throw Error("每个角色最多 20 条事实。"); character.facts.push({ id: "fact-"+crypto.randomUUID(), kind: "state", text: "", citation: null }); render(); })); form.append(card);
    }
    const addCharacter = button("添加角色", () => { if (draft.characters.length >= 30) throw Error("最多 30 个角色。"); draft.characters.push({ id: "character-"+crypto.randomUUID(), name: "", facts: [] }); render(); });
    const note = textarea(reviewNote), checked = mediaCheck("我已逐条核对引用、角色指代与时间范围，并确认这份记忆适用于后续创作", confirmed); note.required = true; note.minLength = 10; note.maxLength = 2000; note.oninput = () => reviewNote = note.value; checked.checkbox.required = true; checked.checkbox.onchange = () => confirmed = checked.checkbox.checked;
    add(form, addCharacter, field("审核与变更说明（10–2000 字，只保留在本机）", note), checked.label);
    const submit = node("button", "primary", "保存为已审核的新版本"); submit.type = "submit"; form.append(submit);
    form.onsubmit = async event => {
      event.preventDefault(); if (!form.reportValidity()) return;
      if (draft.characters.some(c => !c.facts.length || c.facts.some(f => !f.citation))) return toast("每个角色至少保留一条有引用的事实，或移除暂不使用的角色。");
      const restore = mediaFreeze(form);
      try { await api(`/api/series/${seriesId}/memory`, { payload: draft, series_version: memoryState.series_version, memory_version: originalVersion, note: reviewNote, reviewed: confirmed }); toast("角色事实已保存为新版本。旧章保留原快照。"); if (mediaCurrent(box)) { closeModal(); await navigate("books"); await storyMemoryDialog(seriesId); } }
      catch (error) { toast(error.message); } finally { restore(); }
    };
    modal(box);
  }
  render();
}


async function continuityDialog(seriesId) {
  const [proposals, memory] = await Promise.all([api(`/api/series/${seriesId}/continuity`), api(`/api/series/${seriesId}/memory`)]);
  const box = node("div", "media-form");
  add(box, node("h2", "", "从已接受章节提出候选事实"), node("p", "mini-note", "只读取本系列最近接受章节的最后一个文字步骤和当前角色事实。先保存冻结计划，再由你明确制作；建议不会自动更新记忆。"));
  if (memory.pending_run) box.append(empty("已有待完成章节，先完成或拒绝该章再规划新建议。旧建议仍可查看，但不能覆盖新进度。"));
  else {
    const budget = timelineNumber(1, 0, 100000, 0.01), local = mediaCheck("仅使用本地文字模型", true);
    let reservation = null;
    add(box, field("建议阶段预算（配置估计单位）", budget), local.label, button("保存连续性建议计划", async () => {
      const settings = { budget: Number(budget.value), local_only: local.checkbox.checked, max_latency: 300 }, fingerprint = JSON.stringify(settings);
      if (!reservation || reservation.fingerprint !== fingerprint) reservation = { id: "continuity-"+crypto.randomUUID(), key: crypto.randomUUID(), fingerprint };
      const proposal = await api("/api/continuity", { id: reservation.id, series: seriesId, settings }, reservation.key);
      if (mediaCurrent(box)) { closeModal(); await openRun(proposal.run_id); }
    }, "primary"));
  }
  for (const proposal of proposals) {
    const card = node("section", "research-card"); add(card, node("h3", "", proposal.created.slice(0, 16)+" · "+(proposal.state === "accepted" ? "已选择并写入新版记忆" : statuses[proposal.run_status] || proposal.run_status)), node("p", "mini-note", proposal.state === "accepted" ? "写入记忆版本 "+proposal.result_version : proposal.stale ? "系列/记忆已有变化，不可直接采纳。" : "依据当前冻结的章节与记忆快照。"), button("查看模型计划与原始产物", async () => { closeModal(); await openRun(proposal.run_id); }));
    if (["needs_review", "approved"].includes(proposal.run_status)) card.append(button("逐项核对候选事实", () => continuityReviewDialog(proposal.id))); box.append(card);
  }
  if (!proposals.length) box.append(empty("至少先接受一章，再建立第一份建议。系统不重试未知推理，也不会读取未接受的草稿作为事实。"));
  modal(box);
}
async function continuityReviewDialog(id) {
  const proposal = await api("/api/continuity/"+id), box = node("div", "media-form");
  let draft;
  try { draft = await api(`/api/continuity/${id}/draft`); }
  catch (error) { add(box, node("h2", "", "建议暂不可接受"), node("p", "mini-note", "输出未通过结构、引用或产物完整性检查。可查看原始运行，不会自动修复或重做。"), button("查看原始产物", async () => { closeModal(); await openRun(proposal.run_id); })); modal(box); return; }
  add(box, node("h2", "", "核对候选事实与实际原句"), node("p", "", draft.summary), node("p", "mini-note", "模型说明与警告都是候选判断，引用存在不证明语义正确。检查身份指代、时间范围和与既有事实的冲突。未选项目不会写入，现有事实不会被整体清空。"));
  for (const warning of draft.warnings) box.append(node("p", "note-box", warning));
  const choices = [];
  for (const [index, change] of draft.changes.entries()) {
    const card = node("section", "research-card"), oldCharacter = proposal.context.memory.payload.characters.find(c => c.id === change.character), oldFact = oldCharacter?.facts.find(f => f.id === change.fact);
    add(card, node("h3", "", change.name+" · "+(factKinds[change.kind] || change.kind)), node("p", "", change.text));
    if (oldFact) add(card, node("p", "note-box", "此项会替换原事实："+oldFact.text));
    else card.append(node("p", "mini-note", change.character ? "增加到已有角色，不替换其他事实。" : "新增角色；请重点核对是否为既有角色的别名。"));
    add(card, node("blockquote", "lab-quote", change.quote), node("p", "mini-note", "模型理由："+change.reason));
    if (proposal.state !== "accepted" && !proposal.stale) { const choice = mediaCheck("我已逐条核对并选择这一项变更"); choices.push([index, choice.checkbox]); card.append(choice.label); }
    box.append(card);
  }
  if (!draft.changes.length) box.append(empty("模型没有提出可支持的新事实。不会创建空记忆更新；当前事实保持不变。"));
  if (proposal.state === "accepted") add(box, node("p", "subtle", "已保存的选择不可覆盖。记忆版本 "+proposal.result_version), node("p", "mini-note", proposal.review.note), button("查看角色记忆与历史", () => storyMemoryDialog(proposal.series_id)));
  else if (proposal.stale) box.append(node("p", "note-box", "系列/记忆已经变化或有待完成章节。这份建议仅保留查看；请在合适的当前版本重新生成。"));
  else if (proposal.run_status !== "approved") box.append(button("先确认实际建议产物审核通过", async () => { await api(`/api/runs/${proposal.run_id}/approve`, {}); await continuityReviewDialog(id); }));
  else if (draft.changes.length) {
    const note = textarea(); note.minLength = 10; note.maxLength = 2000; note.placeholder = "说明所选事实是否被原句支持、是否与既有设定冲突，以及替换决定的理由。";
    add(box, field("人工审核说明（至少 10 字）", note), button("将选中事实保存到新记忆版本", async () => {
      const selected = choices.filter(([, checkbox]) => checkbox.checked).map(([index]) => index);
      if (!selected.length || note.value.trim().length < 10) throw Error("请逐项选择已核对的事实，并补充至少 10 字审核说明。");
      await api(`/api/continuity/${id}/accept`, { selected, note: note.value, reviewed: true });
      toast("选中事实已写入新版本，其他事实和旧章快照保留。"); if (mediaCurrent(box)) { closeModal(); await navigate("books"); await storyMemoryDialog(proposal.series_id); }
    }, "primary"));
  }
  modal(box);
}
