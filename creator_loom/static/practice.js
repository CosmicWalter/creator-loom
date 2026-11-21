"use strict";
async function practiceReviewSection(root, progress) {
  const summary = panel("隐藏版本标签的改稿比较"), aggregate = progress.blind_revision_reviews;
  add(summary, node("p", "mini-note", "先用同一量表对 A/B 打分，再查看哪个版本是改稿。外部评审身份由你声明，系统未验证独立性；这里的分数变化不代表长期技能或迁移能力提升。"));
  for (const value of aggregate.dimensions) {
    summary.append(node("p", "", `${dimensions[value.dimension] || value.dimension} · ${value.reviewer_kind === "self" ? "自评盲比" : "外部评审声明"} · ${value.comparisons} 对 · 平均改稿差 ${value.mean_revision_delta.toFixed(3)}`));
  }
  if (aggregate.invalidated_comparisons) summary.append(node("p", "mini-note", `${aggregate.invalidated_comparisons} 项比较因源稿或修改稿缺失/变化暂不纳入汇总，请检查原始记录。`));
  const practices = await api("/api/practice?profile="+encodeURIComponent(state.profile));
  if (state.view !== "growth") return;
  for (const practice of practices) {
    const row = node("article", "research-card");
    add(row, node("h3", "", `${stages[practice.step_id] || practice.step_id} · ${dimensions[practice.dimension] || practice.dimension}`), node("p", "mini-note", "练习保存日期："+practice.created.slice(0, 10)), button(practice.reviewed ? "查看已封存比较" : practice.review_id ? "继续 A/B 评审" : "准备 A/B 评审", async () => {
      const review = practice.review_id ? await api("/api/practice-reviews/"+practice.review_id) : await api(`/api/practice/${practice.id}/blind`, {});
      await practiceReviewDialog(review);
    })); summary.append(row);
  }
  if (!practices.length) summary.append(empty("先在已完成作品中保存一份实际修改稿，再准备版本比较。当前 A/B 练习只支持 UTF-8 文字稿，每份不超过 1 MB。"));
  root.append(summary);
}
async function practiceReviewDialog(review) {
  const box = node("div", "media-form"); add(box, node("h2", "", "按同一维度比较两个版本"), node("p", "subtle", dimensions[review.dimension] || review.dimension), node("p", "", review.brief.topic), node("p", "mini-note", reviewQuestions[review.dimension] || review.rubric), node("p", "mini-note", "只比较呈现的作品。不要先查看修改记录或原先自评；本机所有者仍可读取版本映射，内容本身也可能暴露版本。共享上下文在下载包中提供。"));
  const pair = node("div", "lab-pair");
  for (const label of ["A", "B"]) {
    const column = node("section", "timeline-preview"), pre = node("pre", "", "正在核验产物…"); add(column, node("h3", "", label), pre); pair.append(column);
    fetch(`/api/practice-reviews/${review.id}/${label}`).then(async response => { if (!response.ok) throw Error(); pre.textContent = await response.text(); }).catch(() => pre.textContent = "产物缺失或变化，无法评分。");
  }
  box.append(pair);
  const download = node("a", "download", "下载不含版本映射的评审包"); download.href = `/api/practice-reviews/${review.id}/packet`; box.append(download);
  if (review.reviewed) {
    const report = await api(`/api/practice-reviews/${review.id}/report`);
    add(box, node("p", "", `原稿 ${report.scores.original.toFixed(2)} · 修改稿 ${report.scores.revised.toFixed(2)} · 改稿差 ${report.revision_delta.toFixed(3)}`), node("p", "subtle", report.reviewer_kind === "self" ? "记录类型：自评盲比" : "记录类型：外部评审声明（未核实独立性）"), node("p", "", report.rationale));
  } else {
    const form = node("form", "lab-review"), a = timelineNumber("", 0, 1, 0.05), b = timelineNumber("", 0, 1, 0.05), kind = select([["self", "本人评分（自评盲比）"], ["external-declared", "另一评审者提供评分（仅声明，未验证）"]]), rationale = textarea(); rationale.required = true; rationale.minLength = 10; rationale.maxLength = 4000;
    add(form, add(node("div", "field-grid"), field("A 分数（0–1）", a), field("B 分数（0–1）", b)), field("评分来源声明", kind), field("按同一量表说明实际差异（10–4000 字）", rationale));
    const submit = node("button", "primary", "封存比较评分并揭示版本"); submit.type = "submit"; form.append(submit);
    form.onsubmit = async event => {
      event.preventDefault(); if (!form.reportValidity()) return; const restore = mediaFreeze(form);
      try { await api(`/api/practice-reviews/${review.id}/score`, { scores: { A: Number(a.value), B: Number(b.value) }, reviewer_kind: kind.value, rationale: rationale.value }); toast("比较已封存，分数与评分来源声明不可覆盖。"); if (mediaCurrent(box)) { closeModal(); await navigate("growth"); if (state.view === "growth") await practiceReviewDialog(await api("/api/practice-reviews/"+review.id)); } }
      catch (error) { toast(error.message); } finally { restore(); }
    }; box.append(form);
  }
  modal(box);
}
