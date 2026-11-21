"use strict";
const timelineUI = { assets: [], draft: null, loaded: null, cache: new Map(), reviewNotes: new Map(), request: 0, watched: new Set() };
const timelineStates = { draft: "镜头待审核", sealed: "已封存，可渲染", rendering: "渲染中", needs_review: "成片待审核", approved: "已审核", failed: "渲染未完成", interrupted: "渲染已中断" };
function timelineQuery() { return "?profile=" + encodeURIComponent(state.profile); }
function timelineDirty() {
  if (timelineUI.draft) timelineUI.draft.dirty = true;
  const summary = document.querySelector("#timeline-total");
  if (summary && timelineUI.draft) summary.textContent = timelineUI.draft.spec.shots.reduce((n, s) => n + s.duration, 0).toFixed(2) + " 秒 · 未保存的修改";
}
function timelineNumber(value, min = 0, max = 600, step = "any") {
  const n = input(value, "number"); n.min = min; n.max = max; n.step = step; n.required = true; return n;
}
function timelineRefKey(ref) { return JSON.stringify(ref.asset ? ["asset", ref.asset, ref.sha256] : [ref.run, ref.step, ref.file, ref.sha256]); }
function timelineVideo(ref) { return ref.kind === "video" || Boolean(ref.file?.endsWith(".mp4")); }
async function timelineAsset(ref) {
  const found = timelineUI.assets.find(a => timelineRefKey(a.ref) === timelineRefKey(ref));
  if (found) return found;
  if (ref.asset) {
    const asset = await api("/api/assets/" + ref.asset);
    return { key: "asset/" + asset.id, ref, title: asset.payload.title, kind: asset.payload.kind };
  }
  const key = timelineRefKey(ref);
  if (!timelineUI.cache.has(key)) timelineUI.cache.set(key, (async () => {
    const run = await api("/api/runs/" + ref.run), step = run.steps.find(s => s.id === ref.step);
    if (!step?.result) throw Error("源素材尚不可用。");
    const files = [step.result, ...step.result.supplements], index = files.findIndex(f => f.file === ref.file && f.sha256 === ref.sha256);
    if (index < 0) throw Error("源素材与保存版本不一致。");
    return { key: ref.run + "/" + ref.step + "/" + (index === 0 ? "main" : "s" + (index - 1)), ref, title: run.brief.topic,
      kind: ref.file.endsWith(".wav") ? "audio" : ref.file.endsWith(".mp4") ? "video" : "image" };
  })());
  return timelineUI.cache.get(key);
}
async function timelinePreview(ref, parent, shot) {
  const waiting = node("p", "mini-note", "正在核验源素材…"); parent.append(waiting);
  try {
    const asset = await timelineAsset(ref), info = await api("/api/timeline-assets/" + asset.key);
    if (!parent.isConnected) return;
    if (info.ref.sha256 !== ref.sha256) throw Error("素材发生变化，请检查原作品。");
    waiting.remove();
    const preview = node(info.kind === "image" ? "img" : info.kind);
    if (info.kind === "image") preview.alt = "镜头源图像预览";
    else {
      preview.controls = true; preview.preload = "metadata";
      if (shot && info.kind === "video") {
        preview.addEventListener("loadedmetadata", () => { preview.currentTime = shot.in || 0; });
        preview.addEventListener("play", () => {
          if (preview.currentTime < shot.in || preview.currentTime >= shot.in + shot.duration) preview.currentTime = shot.in;
        });
        preview.addEventListener("timeupdate", () => { if (preview.currentTime >= shot.in + shot.duration) preview.pause(); });
      }
    }
    preview.src = info.preview; parent.append(preview);
    parent.append(node("p", "mini-note", "源素材预览。画幅、裁切与运动以渲染结果为准。"));
  } catch (error) { waiting.textContent = error.message; }
}
async function timelineView() {
  const root = $("#content");
  const [timelines, sources] = await Promise.all([api("/api/timelines" + timelineQuery()), api("/api/timeline-assets" + timelineQuery())]);
  if (state.view !== "timelines") return;
  timelineUI.assets = sources.assets;
  add(root, title("EDIT · LISTEN · REVIEW", "把镜头，排成你的叙事节奏。", "从已审核作品中选择画面与声音，安排镜头和字幕。逐镜头确认，再渲染并审核成片。"));
  const tools = node("div", "toolbar");
  tools.append(button("新建剪辑", () => {
    if (timelineUI.draft && !confirm("已有未保存的剪辑，确定放弃它并新建？")) return;
    timelineUI.draft = { id: "edit-" + crypto.randomUUID(), profile: state.profile, baseVersion: null, dirty: false, saveKey: null,
      spec: { title: "", width: 1280, height: 720, fps: 24, shots: [], narration: null, music: null, captions: [] } };
    renderTimelineEditor();
  }, "primary"));
  if (timelineUI.draft?.profile === state.profile) tools.append(button("继续未保存的剪辑", renderTimelineEditor));
  root.append(tools);
  const unavailable = (sources.unavailable_runs || 0) + (sources.unavailable_assets || 0);
  if (unavailable) root.append(node("p", "mini-note", `${unavailable} 份源作品或导入素材缺失或变化，已暂不列入素材选择。`));
  const cards = node("div", "cards");
  for (const timeline of timelines) {
    const card = button("", () => openTimeline(timeline.id), "work-card");
    add(card, node("div", "work-icon", "▥"), node("h3", "", timeline.title), node("p", "", `${timeline.duration.toFixed(2)} 秒 · 版本 ${timeline.version}`), chip(timelineStates[timeline.state] || timeline.state));
    cards.append(card);
  }
  root.append(timelines.length ? cards : empty("还没有剪辑。先在作品档案审核图片、视频或音频，再新建第一份剪辑。"));
  root.append(node("p", "mini-note", "素材选择展示当前偏好档案最近 300 份已审核作品与 300 份已审核导入素材。偏好档案用于组织内容，不是独立的用户权限。"));
}
function timelineEditorHeader(titleText) {
  state.view = "timeline-edit";
  $("#breadcrumb").textContent = "工作空间 / 剪辑台 / 编辑";
  const root = $("#content"); root.classList.add("timeline-content"); root.replaceChildren();
  root.append(title("YOUR EDIT", titleText, "修改先保留在当前页面内存中，保存后才创建不可变版本。离开导航后仍可回到剪辑台继续；关闭或刷新页面前请保存。"));
  return root;
}
function renderTimelineEditor() {
  const draft = timelineUI.draft;
  if (!draft) return;
  const spec = draft.spec, root = timelineEditorHeader(draft.baseVersion ? "为作品，打磨一个新版本。" : "从第一个镜头开始。"), form = node("form", "timeline-editor");
  const basics = panel("创作设置"), name = input(spec.title), canvas = select([["1280x720", "横屏 · 1280 × 720"], ["720x1280", "竖屏 · 720 × 1280"], ["640x360", "横屏 · 640 × 360"], ["360x640", "竖屏 · 360 × 640"]], `${spec.width}x${spec.height}`), fps = select([["24", "24 帧 / 秒"], ["25", "25 帧 / 秒"], ["30", "30 帧 / 秒"]], String(spec.fps));
  name.required = true; name.maxLength = 200; name.oninput = () => { spec.title = name.value; timelineDirty(); };
  canvas.onchange = () => { [spec.width, spec.height] = canvas.value.split("x").map(Number); timelineDirty(); };
  fps.onchange = () => { spec.fps = Number(fps.value); for (const shot of spec.shots) shot.duration = Math.max(Math.ceil(spec.fps / 4), Math.round(shot.duration * spec.fps)) / spec.fps; timelineDirty(); renderTimelineEditor(); };
  add(basics, field("作品标题", name), add(node("div", "field-grid"), field("画幅", canvas), field("播放帧率", fps)));
  const total = node("p", "mini-note", spec.shots.reduce((n, s) => n + s.duration, 0).toFixed(2) + " 秒 · " + spec.shots.length + " 个镜头"); total.id = "timeline-total"; basics.append(total); form.append(basics);
  const shots = panel("画面与镜头顺序");
  for (const [index, shot] of spec.shots.entries()) {
    const row = node("article", "timeline-shot"), head = node("div", "timeline-shot-head"), preview = node("div", "timeline-preview");
    add(head, node("h3", "", "镜头 " + (index + 1)), add(node("div", "toolbar"), button("前移", () => { if (index) { [spec.shots[index - 1], spec.shots[index]] = [shot, spec.shots[index - 1]]; timelineDirty(); renderTimelineEditor(); } }), button("后移", () => { if (index + 1 < spec.shots.length) { [spec.shots[index + 1], spec.shots[index]] = [shot, spec.shots[index + 1]]; timelineDirty(); renderTimelineEditor(); } }), button("移除镜头", () => { spec.shots.splice(index, 1); timelineDirty(); renderTimelineEditor(); })));
    const seconds = timelineNumber(Number(shot.duration.toFixed(6)), 0.25, 120), start = timelineNumber(shot.in || 0, 0, 3600), motion = select([["still", "保持原画面"], ["zoom-in", "居中缓慢推近（仅图片）"]], shot.motion || "still");
    seconds.onchange = () => { shot.duration = Math.max(Math.ceil(spec.fps / 4), Math.round(Number(seconds.value) * spec.fps)) / spec.fps; seconds.value = Number(shot.duration.toFixed(6)); timelineDirty(); };
    start.oninput = () => { shot.in = Number(start.value); timelineDirty(); };
    motion.onchange = () => { shot.motion = motion.value; timelineDirty(); };
    if (!timelineVideo(shot.source)) { start.value = 0; start.disabled = true; }
    else motion.disabled = true;
    add(row, head, preview, add(node("div", "field-grid"), field("时长（秒，自动对齐帧）", seconds), field("源视频入点（秒）", start), field("画面运动", motion)));
    shots.append(row); timelinePreview(shot.source, preview, shot);
  }
  const available = timelineUI.assets.filter(a => a.kind !== "audio"), source = select(available.map((a, i) => [String(i), a.title.slice(0, 60) + " · " + (stages[a.stage] || a.stage)]));
  if (!available.length) shots.append(empty("没有可用画面。请先到作品档案审核图片或视频。"));
  else add(shots, field("添加已审核画面", source), button("添加镜头", async () => {
    if (spec.shots.length >= 120) throw Error("一份剪辑最多 120 个镜头。");
    const selected = available[Number(source.value)], info = await api("/api/timeline-assets/" + selected.key);
    const seconds = info.duration ? Math.min(3, Math.floor(info.duration * spec.fps) / spec.fps) : 3;
    if (seconds < 0.25) throw Error("该片段不足以生成一个镜头。");
    spec.shots.push({ id: "shot-" + crypto.randomUUID(), source: info.ref, duration: seconds, in: 0, motion: "still" });
    timelineDirty(); if (state.view === "timeline-edit" && timelineUI.draft === draft) renderTimelineEditor();
  }));
  form.append(shots);
  const sounds = panel("旁白与音乐"), audio = timelineUI.assets.filter(a => a.kind === "audio");
  for (const role of ["narration", "music"]) {
    const box = node("div", "timeline-audio"), track = spec[role], choices = [["", "不使用此音轨"], ...audio.map((a, i) => [String(i), a.title.slice(0, 60) + " · " + (stages[a.stage] || a.stage)])];
    let current = track ? audio.findIndex(a => timelineRefKey(a.ref) === timelineRefKey(track.source)) : -1;
    if (track && current < 0) choices.push(["retained", "保留已保存的源音轨"]);
    const pick = select(choices, track ? current < 0 ? "retained" : String(current) : "");
    pick.onchange = () => { spec[role] = pick.value === "" ? null : { source: audio[Number(pick.value)].ref, in: 0, gain: role === "music" ? 0.15 : 1, loop: false }; timelineDirty(); renderTimelineEditor(); };
    box.append(field(role === "narration" ? "旁白音轨" : "音乐音轨", pick));
    if (track) {
      const gain = timelineNumber(track.gain, 0, 2, 0.05), start = timelineNumber(track.in, 0, 3600), preview = node("div", "timeline-preview audio-preview");
      gain.oninput = () => { track.gain = Number(gain.value); timelineDirty(); }; start.oninput = () => { track.in = Number(start.value); timelineDirty(); };
      add(box, add(node("div", "field-grid"), field("音量倍数（0–2）", gain), field("音频入点（秒）", start)), preview);
      if (role === "music") { const loop = input("", "checkbox"); loop.checked = track.loop; loop.onchange = () => { track.loop = loop.checked; if (loop.checked) { track.in = 0; start.value = 0; } timelineDirty(); }; box.append(field("从头循环音乐（入点需为 0）", loop)); }
      timelinePreview(track.source, preview);
    }
    sounds.append(box);
  }
  sounds.append(node("p", "mini-note", "原视频音轨不进入混音。旁白不足时补静音；较长音轨裁至成片时长。音乐需要你确认有权使用。")); form.append(sounds);
  const captions = panel("字幕与时间"), end = spec.shots.reduce((n, s) => n + s.duration, 0);
  for (const [index, cue] of spec.captions.entries()) {
    const row = node("div", "timeline-caption"), start = timelineNumber(cue.start), stop = timelineNumber(cue.end), text = input(cue.text); text.required = true; text.maxLength = 500;
    start.oninput = () => { cue.start = Number(start.value); timelineDirty(); }; stop.oninput = () => { cue.end = Number(stop.value); timelineDirty(); }; text.oninput = () => { cue.text = text.value; timelineDirty(); };
    add(row, field("开始（秒）", start), field("结束（秒）", stop), field("字幕 " + (index + 1), text), button("移除", () => { spec.captions.splice(index, 1); timelineDirty(); renderTimelineEditor(); })); captions.append(row);
  }
  add(captions, button("添加字幕", () => { const start = spec.captions.at(-1)?.end || 0; if (start >= end) throw Error("请先增加镜头时长，或调整已有字幕。"); if (spec.captions.length >= 1000) throw Error("最多 1000 条字幕。"); spec.captions.push({ start, end: Math.min(start + 2, end), text: "" }); timelineDirty(); renderTimelineEditor(); }), node("p", "mini-note", "按顺序填写不重叠的时间与纯文本。当前不自动识别语音；字幕不会烧录进画面，可在支持的播放器中选择显示。")); form.append(captions);
  const save = node("button", "primary", draft.baseVersion ? "保存为新版本" : "保存剪辑"); save.type = "submit";
  form.onsubmit = async event => {
    event.preventDefault(); if (!form.reportValidity()) return;
    if (!spec.shots.length) return toast("请先添加一个镜头。");
    const controls = [...form.querySelectorAll("input,select,textarea,button")].map(control => [control, control.disabled]);
    for (const [control] of controls) control.disabled = true;
    try {
      const body = draft.baseVersion ? { spec, version: draft.baseVersion } : { id: draft.id, spec, profile: draft.profile };
      const serialized = JSON.stringify(body); if (draft.keyBody !== serialized) { draft.keyBody = serialized; draft.saveKey = crypto.randomUUID(); }
      const saved = await api(draft.baseVersion ? `/api/timelines/${draft.id}/revise` : "/api/timelines", body, draft.saveKey);
      const wasCurrent = timelineUI.draft === draft;
      if (wasCurrent) timelineUI.draft = null;
      toast("剪辑已保存。请逐镜头审核这个版本。");
      if (wasCurrent && state.view === "timeline-edit") await openTimeline(saved.id, saved.version);
    } catch (error) { toast(error.message); } finally { for (const [control, disabled] of controls) control.disabled = disabled; }
  };
  add(form, add(node("div", "toolbar"), save, button("返回剪辑列表", () => navigate("timelines")))); root.append(form);
}
function watchTimelineAction(action, name, version) {
  if (timelineUI.watched.has(action)) return; timelineUI.watched.add(action); let attempts = 0;
  async function poll() {
    try {
      const timeline = await api(`/api/timelines/${name}?version=${version}`), current = timeline.actions.find(a => a.id === action);
      if (current && ["queued", "running"].includes(current.status) && attempts++ < 900) { setTimeout(poll, 1500); return; }
      timelineUI.watched.delete(action);
      if (current?.error) toast(current.error);
      if (current && ["queued", "running"].includes(current.status)) toast("任务仍在后台运行，可稍后刷新查看。未重新提交。");
      if (state.view === "timeline-detail" && timelineUI.loaded?.id === name && timelineUI.loaded.version === version) await openTimeline(name, version);
    } catch (error) { timelineUI.watched.delete(action); toast(error.message); }
  }
  setTimeout(poll, 1000);
}
async function openTimeline(name, version) {
  state.view = "timeline-detail";
  const request = ++timelineUI.request;
  const timeline = await api("/api/timelines/" + name + (version ? "?version=" + version : ""));
  if (state.view !== "timeline-detail" || request !== timelineUI.request) return;
  timelineUI.loaded = timeline;
  const root = $("#content"); root.classList.add("timeline-content"); root.replaceChildren(); $("#breadcrumb").textContent = "工作空间 / 剪辑台 / 审核";
  const heading = node("div", "detail-title"), label = node("div"), tools = node("div", "toolbar"), historical = timeline.version !== timeline.current_version;
  add(label, node("p", "eyebrow", `TIMELINE · 版本 ${timeline.version}`), node("h1", "", timeline.spec.title), chip(timelineStates[timeline.state] || timeline.state), node("p", "mini-note", `${timeline.spec.duration.toFixed(2)} 秒 · ${timeline.spec.width} × ${timeline.spec.height} · ${timeline.spec.fps} 帧/秒`));
  tools.append(button("返回列表", () => navigate("timelines")), button("刷新状态", () => openTimeline(name, timeline.version)));
  if (!timeline.actions.some(a => ["queued", "running"].includes(a.status))) tools.append(button("基于此版编辑", async () => {
    if (timelineUI.draft && !confirm("确定放弃未保存的剪辑，改为编辑这个版本？")) return;
    const sources = await api("/api/timeline-assets" + timelineQuery()); timelineUI.assets = sources.assets;
    const spec = JSON.parse(JSON.stringify(timeline.spec)); delete spec.duration;
    timelineUI.draft = { id: name, profile: timeline.profile, baseVersion: timeline.current_version, spec, dirty: false, saveKey: null }; renderTimelineEditor();
  }));
  const versions = select(timeline.versions.map(v => [String(v.version), `版本 ${v.version} · ${timelineStates[v.state] || v.state}`]), String(timeline.version));
  versions.setAttribute("aria-label", "查看历史版本"); versions.onchange = () => openTimeline(name, Number(versions.value)).catch(e => toast(e.message)); tools.append(versions);
  add(heading, label, tools); root.append(heading);
  if (historical) root.append(node("p", "mini-note", "正在查看历史版本。审核与渲染只针对当前版本；历史交付仍可核验和下载。"));
  const sequence = panel("镜头顺序"), strip = node("ol", "timeline-strip");
  let position = 0;
  for (const [index, shot] of timeline.spec.shots.entries()) { strip.append(node("li", "", `${index + 1} · ${position.toFixed(2)}–${(position + shot.duration).toFixed(2)} 秒`)); position += shot.duration; } sequence.append(strip); root.append(sequence);
  const reviewSummary = node("div", "toolbar"), approved = timeline.reviews.filter(r => r.decision === "approve").length;
  reviewSummary.append(node("p", "subtle", `${approved} / ${timeline.spec.shots.length} 个镜头审核通过`));
  if (!historical && timeline.state === "draft") { const seal = button("封存已审核镜头", async () => { await api(`/api/timelines/${name}/seal`, { version: timeline.version }); await openTimeline(name); }, "primary"); seal.disabled = approved !== timeline.spec.shots.length; reviewSummary.append(seal); }
  const active = timeline.actions.find(a => ["queued", "running"].includes(a.status));
  if (active) { reviewSummary.append(chip("已排队或渲染中")); watchTimelineAction(active.id, name, timeline.version); }
  if (!historical && timeline.state === "sealed" && !active) reviewSummary.append(button("开始本机渲染", async () => { const action = await api(`/api/timelines/${name}/render`, { version: timeline.version }, crypto.randomUUID()); await openTimeline(name); watchTimelineAction(action.id, name, timeline.version); }, "primary"));
  if (["failed", "interrupted", "rendering"].includes(timeline.state) && !active) reviewSummary.append(node("p", "mini-note", "没有重新提交。若旧任务已中断，可基于此版编辑并保存新版本。"));
  root.append(reviewSummary);
  for (const [index, shot] of timeline.spec.shots.entries()) {
    const p = panel("镜头 " + (index + 1)), preview = node("div", "timeline-preview"), review = timeline.reviews.find(r => r.shot_id === shot.id);
    add(p, preview, node("p", "subtle", `时长 ${shot.duration.toFixed(2)} 秒 · 源入点 ${shot.in} 秒 · ${shot.motion === "zoom-in" ? "居中缓慢推近" : "保持原画面"}`)); timelinePreview(shot.source, preview, shot);
    if (review) add(p, chip(review.decision === "approve" ? "审核通过" : "需要修改", review.decision !== "approve"), node("p", "mini-note", review.note));
    else if (!historical && timeline.state === "draft") {
      const noteKey = `${name}/${timeline.version}/${shot.id}`, note = textarea(timelineUI.reviewNotes.get(noteKey) || ""); note.oninput = () => timelineUI.reviewNotes.set(noteKey, note.value); note.minLength = 5; note.maxLength = 2000; note.placeholder = "检查来源、构图、时长、叙事关系和使用权利，并写下理由。";
      add(p, field("审核说明（至少 5 字）", note), add(node("div", "toolbar"), ...[["approve", "镜头审核通过"], ["reject", "需要修改"]].map(([decision, text]) => button(text, async () => { if (note.value.trim().length < 5) throw Error("请补充至少 5 字的审核说明。"); await api(`/api/timelines/${name}/shot`, { version: timeline.version, shot: shot.id, decision, note: note.value }); timelineUI.reviewNotes.delete(noteKey); await openTimeline(name, timeline.version); }))));
    }
    root.append(p);
  }
  const sound = panel("声音与字幕设置");
  for (const role of ["narration", "music"]) { const track = timeline.spec[role]; sound.append(node("p", "subtle", (role === "music" ? "音乐" : "旁白") + (track ? ` · 音量 ${track.gain} 倍 · 入点 ${track.in} 秒${track.loop ? " · 从头循环" : ""}` : " · 未使用"))); if (track) { const preview = node("div", "timeline-preview audio-preview"); sound.append(preview); timelinePreview(track.source, preview); } }
  for (const cue of timeline.spec.captions) sound.append(node("p", "caption-summary", `${cue.start}–${cue.end} 秒 · ${cue.text}`));
  sound.append(node("p", "mini-note", "确认音轨与字幕配合后，再审核实际渲染的成片。")); root.append(sound);
  if (["needs_review", "approved"].includes(timeline.state)) {
    const p = panel("成片预览与交付"), video = node("video", "timeline-film"), base = `/api/timeline-media/${name}/${timeline.version}/`;
    video.controls = true; video.preload = "metadata"; video.src = base + "film.mp4";
    if (timeline.spec.captions.length) { const track = node("track"); track.kind = "subtitles"; track.label = "作品字幕"; track.srclang = "und"; track.src = base + "captions.vtt"; video.append(track); }
    add(p, video, node("p", "mini-note", "检查完整画面、剪辑点、声音和字幕。播放器的字幕菜单可选择显示；下载不代表平台投稿。"));
    if (!historical && timeline.state === "needs_review") p.append(button("确认成片审核通过", async () => { await api(`/api/timelines/${name}/approve`, { version: timeline.version }); await openTimeline(name, timeline.version); }, "primary"));
    if (timeline.state === "approved") { const link = node("a", "download", "下载审核后的交付包"); link.href = `/api/timeline-export/${name}/${timeline.version}`; p.append(link); }
    root.append(p);
  }
}
window.addEventListener("beforeunload", event => { if (timelineUI.draft?.dirty) { event.preventDefault(); event.returnValue = ""; } });
