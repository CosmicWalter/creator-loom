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
