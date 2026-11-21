"use strict";
const mediaUI = { project: null, request: 0 };
const assetStates = { needs_review: "等待素材审核", approved: "已审核可复用", rejected: "未通过审核" };
const musicStates = { planned: "方案待制作与审核", handed_off: "交接包已准备", external_reported: "外部结果由用户报备", result_attached: "本机结果已审核采纳" };
function mediaCheck(text, checked = false) {
  const checkbox = input("", "checkbox"); checkbox.checked = checked;
  return { checkbox, label: add(node("label", "check"), checkbox, document.createTextNode(text)) };
}
function mediaFreeze(form) {
  const controls = [...form.querySelectorAll("input,textarea,select,button")].map(c => [c, c.disabled]);
  controls.forEach(([c]) => c.disabled = true);
  return () => controls.forEach(([c, disabled]) => c.disabled = disabled);
}
function mediaCurrent(box) { return $("#modal").open && $("#modal-content").contains(box); }
function mediaFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onerror = () => reject(Error("无法读取所选文件。"));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]); reader.readAsDataURL(file);
  });
}
function mediaPreview(asset, parent) {
  const preview = node(asset.payload.kind === "image" ? "img" : asset.payload.kind);
  if (asset.payload.kind === "image") preview.alt = "规范化后的源素材";
  else { preview.controls = true; preview.preload = "metadata"; }
  preview.src = `/api/assets/${asset.id}/media`; preview.addEventListener("error", () => parent.append(node("p", "mini-note", "素材无法读取或已发生变化，请刷新并检查审核状态。")), { once: true }); parent.append(preview);
}
async function mediaView() {
  const profile = encodeURIComponent(state.profile), [assets, projects] = await Promise.all([api("/api/assets?profile="+profile), api("/api/music?profile="+profile)]);
  if (state.view !== "assets") return;
  const root = $("#content"); root.classList.add("timeline-content");
  add(root, title("SOURCES · RIGHTS · MUSIC", "让每一份素材，都有清楚的来处。", "导入你有权使用的图片、音频和视频，核验实际产物与署名，再用于歌词方案、外部音乐制作和剪辑。"));
  add(root, add(node("div", "toolbar"), button("导入授权素材", () => assetImport(), "primary"), button("新建音乐改编方案", () => musicCreate(assets))));
  const sources = panel("本机素材库"), cards = node("div", "cards");
  for (const asset of assets) {
    const card = button("", () => assetDialog(asset.id), "work-card");
    add(card, node("div", "work-icon", asset.payload.kind === "audio" ? "≋" : asset.payload.kind === "video" ? "▷" : "◒"), node("h3", "", asset.payload.title), node("p", "", { owned: "自有素材", licensed: "已获许可", "public-domain": "公有领域" }[asset.payload.rights]), chip(assetStates[asset.state], asset.state === "rejected")); cards.append(card);
  }
  sources.append(assets.length ? cards : empty("可导入 PNG / JPEG、WAV / MP3 和 MP4。上传前请确认内容与改编用途均获得授权。"));
  sources.append(node("p", "mini-note", "网页单次上传不超过 32 MB；CLI 支持 64 MB。音视频最多十分钟。原始文件仅存本机，规范化文件需审核后才能复用；导入视频不保留原音轨。")); root.append(sources);
  const music = panel("音乐改编方案"), list = node("div", "cards");
  for (const project of projects) {
    const card = button("", () => openMusic(project.id), "work-card");
    add(card, node("div", "work-icon", "♫"), node("h3", "", project.definition.title), node("p", "", musicStates[project.state] || project.state), chip(statuses[project.run_status] || project.run_status)); list.append(card);
  }
  music.append(projects.length ? list : empty("从原创或已授权歌词与参考音频开始。先生成、审核方案，再决定是否准备人工交接包。"));
  music.append(node("p", "mini-note", "歌曲配方生成歌词和音乐方向文字，不分析音频或生成歌曲。Suno 制作由你人工操作；填写的外部链接不等于供应商验证回执。")); root.append(music);
}
function assetImport(origin, attribution = "") {
  const box = node("div", "media-form"), form = node("form"), titleInput = input(), file = input("", "file"), kind = select([["audio", "音频 · WAV / MP3"], ["image", "图片 · PNG / JPEG"], ["video", "视频 · MP4"]]), rights = select([["owned", "我拥有相应权利"], ["licensed", "我已获得相应许可"], ["public-domain", "该素材属于公有领域"]]), note = textarea(), credit = textarea(attribution), license = input(), service = select([["external", "外部 / 本机素材"], ["suno", "Suno 制作结果"]], origin ? "suno" : "external"), reference = input(origin || ""), authorized = mediaCheck("我确认拥有导入、编辑及本次用途所需的权利");
  titleInput.required = true; titleInput.maxLength = 200; file.required = true; file.accept = ".png,.jpg,.jpeg,.wav,.mp3,.mp4"; note.required = true; note.minLength = 10; note.maxLength = 2000; credit.maxLength = 2000; authorized.checkbox.required = true;
  note.placeholder = "简述来源与授权范围，至少 10 字。此说明只保存在本机，不放入交付包。"; credit.placeholder = "需要随素材保留的公开署名、许可说明和来源。许可/公有领域素材必填。"; reference.placeholder = "Suno 歌曲或分享链接，不含查询参数";
  file.addEventListener("change", () => { const type = file.files[0]?.type || ""; if (type.startsWith("image/")) kind.value = "image"; if (type.startsWith("audio/")) kind.value = "audio"; if (type === "video/mp4") kind.value = "video"; });
  let key = crypto.randomUUID(); form.addEventListener("input", () => { key = crypto.randomUUID(); }); form.addEventListener("change", () => { key = crypto.randomUUID(); });
  add(box, node("h2", "", "导入授权素材"), node("p", "mini-note", "不保存原始文件名或设备路径。文件内容仍需你检查；规范化不能替代权利与隐私审核。"), form);
  add(form, field("素材标题", titleInput), field("文件", file), field("素材类型", kind), field("权利声明", rights), field("私有授权说明", note), field("公开署名与许可（随交付保留）", credit), field("公开许可链接（可选 HTTPS）", license), field("制作来源", service), field("来源记录链接（可选，不作为验证回执）", reference), authorized.label);
  const submit = node("button", "primary", "导入并准备审核"); submit.type = "submit"; form.append(submit);
  form.onsubmit = async event => {
    event.preventDefault(); if (!form.reportValidity()) return;
    const chosen = file.files[0]; if (!chosen || chosen.size > 32*1024*1024) return toast("请选择不超过 32 MB 的文件；更大文件可使用 CLI。");
    if (rights.value !== "owned" && !credit.value.trim()) return toast("请填写需要随素材保留的公开署名与许可。");
    const metadata = { title: titleInput.value, kind: kind.value, rights: rights.value, rights_note: note.value, authorized: authorized.checkbox.checked, attribution: credit.value, license_url: license.value.trim(), origin: { service: service.value, reference: reference.value.trim() }, profile: state.profile };
    const restore = mediaFreeze(form); submit.textContent = "正在本机检查并规范化…";
    try { const data = await mediaFile(chosen), asset = await api("/api/assets", { data, metadata }, key); toast("素材已保存在本机，请检查实际产物后审核。"); if (mediaCurrent(box)) { closeModal(); await navigate("assets"); if (state.view === "assets") await assetDialog(asset.id); } }
    catch (error) { toast(error.message); } finally { restore(); submit.textContent = "导入并准备审核"; }
  };
  modal(box);
}
async function assetDialog(name) {
  const asset = await api("/api/assets/"+name), box = node("div", "media-form"), preview = node("div", "timeline-preview");
  add(box, node("h2", "", asset.payload.title), chip(assetStates[asset.state]), preview, node("p", "subtle", "权利声明："+asset.payload.rights), node("p", "mini-note", "本机授权说明："+asset.payload.rights_note), node("p", "subtle", "公开署名："+(asset.payload.attribution || "无额外署名")), node("p", "mini-note", "请检查实际内容、授权范围、隐私和需要保留的署名。导入状态不代表权利已被系统核实。")); mediaPreview(asset, preview);
  if (asset.payload.transform) box.append(node("p", "mini-note", "参考音频处理："+JSON.stringify(asset.payload.transform)));
  if (asset.review) box.append(node("p", "subtle", "审核说明："+asset.review.note));
  if (asset.state === "needs_review") {
    const note = textarea(); note.placeholder = "记录内容、使用权利和实际预览检查结果。"; note.minLength = 5; note.maxLength = 2000;
    add(box, field("审核说明", note), add(node("div", "toolbar"), ...[["approve", "审核通过"], ["reject", "暂不使用"]].map(([decision, label]) => button(label, async () => { if (note.value.trim().length < 5) throw Error("请填写至少 5 字审核说明。"); await api(`/api/assets/${name}/review`, { decision, note: note.value }); closeModal(); await navigate("assets"); }))));
  }
  if (asset.state === "approved") {
    const download = node("a", "download", "下载素材与署名包"); download.href = `/api/assets/${name}/export`; box.append(download);
    if (asset.payload.kind === "audio") box.append(button("制作参考音频处理版本", () => { closeModal(); audioDerive(asset); }));
  }
  modal(box);
}
function audioDerive(asset) {
  const box = node("div", "media-form"), form = node("form"), start = timelineNumber(0, 0, asset.payload.duration), duration = timelineNumber(Math.min(30, asset.payload.duration), 0.1, asset.payload.duration), tempo = timelineNumber(1, 0.5, 2, 0.01), pitch = timelineNumber(0, -12, 12, 0.5), mode = select([["independent", "独立变速与移调"], ["tape", "磁带式联动变速与音高"]]);
  mode.onchange = () => { pitch.disabled = mode.value === "tape"; if (pitch.disabled) pitch.value = 0; };
  let key = crypto.randomUUID(); form.addEventListener("input", () => key = crypto.randomUUID()); form.addEventListener("change", () => key = crypto.randomUUID());
  add(box, node("h2", "", "准备一个可复现的参考片段"), node("p", "mini-note", "这是本机裁切、变速和移调，不是重新编曲。原素材和署名会保留，处理结果需要重新试听审核。"), form);
  add(form, field("输入入点（秒）", start), field("截取的输入时长（秒）", duration), field("处理模式", mode), field("速度倍率（0.5–2）", tempo), field("移调半音（−12–12）", pitch));
  const submit = node("button", "primary", "处理并另存审核版本"); submit.type = "submit"; form.append(submit);
  form.onsubmit = async event => { event.preventDefault(); if (!form.reportValidity()) return; const restore = mediaFreeze(form); try { const result = await api(`/api/assets/${asset.id}/derive`, { settings: { start: Number(start.value), duration: Number(duration.value), tempo: Number(tempo.value), semitones: Number(pitch.value), mode: mode.value } }, key); if (mediaCurrent(box)) { closeModal(); await navigate("assets"); if (state.view === "assets") await assetDialog(result.id); } } catch (error) { toast(error.message); } finally { restore(); } }; modal(box);
}
function musicCreate(assets) {
  const box = node("div", "media-form"), form = node("form"), titleInput = input(), intent = textarea(), lyrics = textarea(), note = textarea(), source = select([["", "不绑定参考音频"], ...assets.filter(a => a.state === "approved" && a.payload.kind === "audio").map(a => [a.id, a.payload.title])]), language = select([["zh", "中文"], ["zh-HK", "粤语 / 中文（需人工校音）"], ["en", "English"]]), budget = timelineNumber(1, 0, 100000, 0.01), local = mediaCheck("仅使用已配置的本地文字模型", true), authorized = mediaCheck("我有权改编所填歌词，并将所选参考用于本次创作");
  titleInput.required = true; titleInput.maxLength = 200; intent.required = true; intent.minLength = 10; intent.maxLength = 2000; lyrics.maxLength = 5000; note.required = true; note.minLength = 10; note.maxLength = 2000; authorized.checkbox.required = true;
  intent.placeholder = "说明语言、节奏、情绪、编曲与希望保留/改变的内容。"; lyrics.placeholder = "填入原创或已获授权的歌词；可保留 Verse / Chorus 段落标签。留空则按意图创作原创歌词。"; note.placeholder = "记录歌词及改编用途的授权范围；只保存在本机。";
  const lyricRights = select([["owned", "原创 / 自有权利"], ["licensed", "歌词已获许可"], ["public-domain", "公有领域歌词"]]), lyricCredit = textarea(), lyricLicense = input();
  lyricCredit.maxLength = 2000; lyricCredit.placeholder = "歌词需要保留的公开署名与许可；非自有歌词必填。";
  const name = "music-"+crypto.randomUUID(); let key = crypto.randomUUID(); form.addEventListener("input", () => key = crypto.randomUUID()); form.addEventListener("change", () => key = crypto.randomUUID());
  add(box, node("h2", "", "音乐改编方案"), node("p", "mini-note", "文字模型只处理标题、创作意图和已授权歌词，不会听取参考音频。该步骤不生成歌曲或自动操作 Suno。"), form);
  add(form, field("方案标题", titleInput), field("创作意图", intent), field("已授权歌词（可选）", lyrics), field("歌词权利类型", lyricRights), field("歌词公开署名与许可", lyricCredit), field("歌词公开许可链接（可选）", lyricLicense), field("参考音频", source), field("目标语言", language), field("方案预算（配置估计单位）", budget), field("私有授权说明", note), local.label, authorized.label);
  const submit = node("button", "primary", "保存方案并查看模型计划"); submit.type = "submit"; form.append(submit);
  form.onsubmit = async event => { event.preventDefault(); if (!form.reportValidity()) return; const restore = mediaFreeze(form); try { const spec = { title: titleInput.value, intent: intent.value, lyrics: lyrics.value, lyrics_rights: lyricRights.value, lyrics_attribution: lyricCredit.value, lyrics_license_url: lyricLicense.value.trim(), rights_note: note.value, adaptation_authorized: authorized.checkbox.checked, profile: state.profile, language: language.value, local_only: local.checkbox.checked, budget: Number(budget.value) }; if (source.value) spec.source = { asset: source.value }; const project = await api("/api/music", { id: name, spec }, key); if (mediaCurrent(box)) { closeModal(); await openMusic(project.id); } } catch (error) { toast(error.message); } finally { restore(); } }; modal(box);
}
async function openMusic(name) {
  state.view = "music-detail"; mediaUI.project = name; const request = ++mediaUI.request, project = await api("/api/music/"+name);
  if (state.view !== "music-detail" || request !== mediaUI.request) return;
  const root = $("#content"); root.classList.add("timeline-content"); root.replaceChildren(); $("#breadcrumb").textContent = "工作空间 / 素材与音乐 / 方案";
  const head = node("div", "detail-title"); add(head, add(node("div"), node("p", "eyebrow", "MUSIC · REVIEWED HANDOFF"), node("h1", "", project.definition.title), chip(musicStates[project.state])), add(node("div", "toolbar"), button("返回素材与音乐", () => navigate("assets")), button("查看文字制作计划与作品", () => openRun(project.run_id)), button("刷新", () => openMusic(name)))); root.append(head);
  const brief = panel("创作意图与参考"); add(brief, node("p", "", project.definition.intent), node("p", "subtle", "文字制作状态："+(statuses[project.run_status] || project.run_status)), node("p", "mini-note", "文字模型没有分析参考音频；没有在 Suno 自动生成或发布。请先查看计划，明确执行并审核歌词与方向产物。"));
  if (project.definition.source) brief.append(button("试听与检查已审核参考", () => assetDialog(project.definition.source.asset))); root.append(brief);
  const handoff = panel("人工交接包");
  if (project.handoff) { const download = node("a", "download", "下载已授权的交接包"); download.href = `/api/music/${name}/handoff`; add(handoff, download, node("p", "mini-note", project.handoff.authorization.include_audio ? "包内包括已审核参考音频及其署名。请自行核对 Suno 表单和上传范围。" : "包内仅含歌词、音乐方向和创作说明；不包含参考音频。"), node("p", "subtle", "交接包准备完成不代表外部任务已经提交。")); }
  else if (project.run_status === "approved") {
    const transfer = mediaCheck("我确认允许方案及所选参考用于外部音乐制作"), include = mediaCheck("将已审核参考音频加入交接包（默认不加入）"), note = textarea(); include.checkbox.disabled = !project.definition.source; note.placeholder = "说明外部使用范围与授权决定，至少 10 字。";
    add(handoff, transfer.label, include.label, field("交接授权说明", note), button("准备本机交接包", async () => { if (!transfer.checkbox.checked || note.value.trim().length < 10) throw Error("请确认外部使用授权并补充说明。"); await api(`/api/music/${name}/handoff`, { transfer_authorized: transfer.checkbox.checked, include_audio: include.checkbox.checked, note: note.value }); await openMusic(name); }, "primary"));
  } else handoff.append(empty("先在文字作品详情中明确执行制作，并检查、审核歌词与音乐方向。")); root.append(handoff);
  if (project.handoff) {
    const external = panel("外部结果记录");
    if (project.external) add(external, node("p", "", project.external.reference), node("p", "mini-note", "该链接由你填写，系统没有向供应商核实任务或生成结果。"), node("p", "subtle", project.external.note));
    else { const reference = input(), note = textarea(); reference.placeholder = "https://suno.com/song/歌曲标识"; note.placeholder = "记录在外部实际完成的操作与结果，至少 10 字。"; add(external, field("Suno 歌曲/分享链接（不含查询参数）", reference), field("操作与结果说明", note), button("保存用户报备记录", async () => { await api(`/api/music/${name}/external`, { reference: reference.value.trim(), note: note.value }); await openMusic(name); })); } root.append(external);
  }
  if (project.external) {
    const result = panel("本机结果导入与采纳");
    if (project.result) add(result, node("p", "", "已绑定审核通过的本机音频。此记录不证明供应商生成过程。"), node("p", "subtle", project.result.note), button("试听已采纳结果", () => assetDialog(project.result.source.asset)), button("进入剪辑台", () => navigate("timelines")));
    else { const assets = await api("/api/assets?profile="+encodeURIComponent(project.definition.profile)+"&state=approved"); if (state.view !== "music-detail" || request !== mediaUI.request) return; const eligible = assets.filter(a => a.payload.kind === "audio" && a.payload.origin.service === "suno" && a.payload.origin.reference === project.external.reference), pick = select(eligible.map(a => [a.id, a.payload.title])), note = textarea();
      add(result, node("p", "mini-note", "先导入你有权使用的外部结果，选择 Suno 来源并填写同一个记录链接，完成素材审核后再采纳。"), button("导入本机结果音频", () => assetImport(project.external.reference, project.required_attributions.join("\n"))));
      if (eligible.length) add(result, field("选择已审核的匹配结果", pick), field("采纳说明（至少 10 字）", note), button("绑定并采纳本机结果", async () => { await api(`/api/music/${name}/attach`, { asset: pick.value, note: note.value }); await openMusic(name); }, "primary")); else result.append(empty("还没有来源记录匹配的已审核音频。可先到素材库试听并完成审核。"));
    }
    root.append(result);
  }
}
