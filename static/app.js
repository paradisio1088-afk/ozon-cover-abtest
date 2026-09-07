"use strict";
const $ = (id) => document.getElementById(id);
let STATE = null;

async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body || {}),
  });
  const data = await r.json();
  if (!r.ok || data.ok === false) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

function msg(id, text, kind = "info") {
  const el = $(id);
  if (!text) { el.style.display = "none"; el.innerHTML = ""; return; }
  el.className = "msg " + kind;
  el.style.display = "block";
  el.textContent = text;
}

function fmt(n) { return (n ?? 0).toLocaleString("ru-RU"); }
function pct(x) { return (100 * (x || 0)).toFixed(2) + "%"; }

// ─── загрузка состояния ─────────────────────────────────────────────
async function loadState() {
  STATE = await api("/api/state");
  renderSecrets();
  renderProduct();
  renderCampaigns();
  renderVariants();
  renderParams();
  renderStatus();
  renderResults();
}

function renderSecrets() {
  const s = STATE.secrets;
  const set = (id, v) => { if (!$(id).dataset.touched) $(id).placeholder = v || $(id).placeholder; };
  $("s_ozon_client_id").value = s.ozon_client_id || "";
  set("s_ozon_api_key", s.ozon_api_key);
  $("s_perf_client_id").value = s.perf_client_id || "";
  set("s_perf_client_secret", s.perf_client_secret);
  $("s_github_repo").value = s.github_repo || "";
  set("s_github_token", s.github_token);
}

["s_ozon_client_id","s_ozon_api_key","s_perf_client_id","s_perf_client_secret",
 "s_github_repo","s_github_token"].forEach(id =>
  $(id).addEventListener("input", () => $(id).dataset.touched = "1"));

async function saveSecrets() {
  const body = {};
  const map = { s_ozon_client_id:"ozon_client_id", s_ozon_api_key:"ozon_api_key",
    s_perf_client_id:"perf_client_id", s_perf_client_secret:"perf_client_secret",
    s_github_repo:"github_repo", s_github_token:"github_token" };
  for (const [el, key] of Object.entries(map)) {
    const v = $(el).value.trim();
    if (v && !v.includes("•")) body[key] = v;
  }
  try {
    await api("/api/secrets", body);
    ["s_ozon_api_key","s_perf_client_secret","s_github_token"].forEach(id => {
      $(id).value = ""; delete $(id).dataset.touched;
    });
    await loadState();
    msg("conn-msg", "Ключи сохранены.", "ok");
  } catch (e) { msg("conn-msg", e.message, "err"); }
}

async function checkAll() {
  msg("conn-msg", "Проверяю…", "info");
  $("conn-status").innerHTML = "";
  try {
    const { ...r } = await api("/api/check", {});
    const chip = (name, o) => {
      const ok = o && o.ok;
      const extra = ok ? (o.campaigns != null ? ` (${o.campaigns} кампаний)`
                          : o.repo ? ` (${o.repo}${o.empty ? ", пустой — добавь README" : ""})` : " ✓")
                       : ": " + (o && o.error || "нет");
      return `<span class="status ${ok?'ok':'err'}">${name}${extra}</span>`;
    };
    $("conn-status").innerHTML =
      chip("Seller API", r.ozon) + chip("Performance API", r.perf) + chip("GitHub", r.github);
    msg("conn-msg", "", "");
  } catch (e) { msg("conn-msg", e.message, "err"); }
}

// ─── товар ─────────────────────────────────────────────────────────
async function findProduct() {
  const offer_id = $("offer_id").value.trim();
  if (!offer_id) return msg("product-msg", "Введите артикул", "err");
  msg("product-msg", "Ищу…", "info");
  try {
    const r = await api("/api/product", { offer_id });
    msg("product-msg", "", "");
    showProduct(r);
    await loadState();
  } catch (e) { msg("product-msg", e.message, "err"); }
}
function showProduct(r) {
  $("product-box").style.display = "block";
  $("pid-val").textContent = r.product_id;
  $("cover-url").textContent = r.current_cover || "—";
  if (r.current_cover) $("cover-img").src = r.current_cover;
}
function renderProduct() {
  const c = STATE.config;
  if (c.offer_id) $("offer_id").value = c.offer_id;
  if (c.product_id) { $("pid-val").textContent = c.product_id; $("product-box").style.display = "block"; }
}

// ─── кампании ──────────────────────────────────────────────────────
async function loadCampaigns() {
  msg("camp-msg", "Загружаю…", "info");
  try {
    const r = await api("/api/campaigns", {});
    STATE.campaigns_cache = r.campaigns;
    renderCampaigns();
    msg("camp-msg", r.campaigns.length ? "" : "Кампаний не найдено", r.campaigns.length ? "" : "err");
  } catch (e) { msg("camp-msg", e.message, "err"); }
}
function renderCampaigns() {
  const rows = STATE.campaigns_cache || [];
  const chosen = new Set((STATE.config.campaign_ids || []).map(String));
  if (!rows.length) { $("camp-list").innerHTML = '<p class="muted">список не загружен</p>'; return; }
  $("camp-list").innerHTML = rows.map(c => `
    <label style="margin:4px 0"><input type="checkbox" style="width:auto" value="${c.id}"
      ${chosen.has(String(c.id)) ? "checked" : ""} onchange="saveCampaigns()">
      <span class="mono">${c.id}</span> — ${c.title || "(без названия)"}
      <span class="muted">${c.state === "CAMPAIGN_STATE_RUNNING" ? "активна" : c.state}</span></label>`).join("");
}
async function saveCampaigns() {
  const ids = [...document.querySelectorAll('#camp-list input:checked')].map(i => i.value);
  try { await api("/api/config", { campaign_ids: ids }); STATE.config.campaign_ids = ids; }
  catch (e) { msg("camp-msg", e.message, "err"); }
}

// ─── варианты фото ─────────────────────────────────────────────────
function fileToB64(f) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(f);
  });
}
async function uploadPhotos(replace) {
  const files = [...$("files").files];
  if (!files.length) return msg("photos-msg", "Выберите файлы", "err");
  msg("photos-msg", `Загружаю ${files.length} фото в GitHub…`, "info");
  try {
    const photos = [];
    for (const f of files) photos.push({ name: f.name.replace(/\.[^.]+$/, ""), filename: f.name, data_b64: await fileToB64(f) });
    const r = await api("/api/photos", { photos, replace });
    STATE.config.variants = r.variants;
    $("files").value = "";
    renderVariants();
    msg("photos-msg", `Готово. Вариантов: ${r.variants.length}`, "ok");
  } catch (e) { msg("photos-msg", e.message, "err"); }
}
function renderVariants() {
  const v = STATE.config.variants || [];
  $("variants").innerHTML = v.map((x, i) => `
    <div class="variant">
      <img src="${x.url}" alt="">
      <input type="text" value="${(x.name || "").replace(/"/g,'&quot;')}"
        onchange="renameVariant(${i}, this.value)">
      <button class="ghost small del" onclick="deleteVariant(${i})">удалить</button>
    </div>`).join("");
}
async function deleteVariant(i) {
  if (!confirm("Удалить вариант?")) return;
  const r = await api("/api/photos/delete", { index: i });
  STATE.config.variants = r.variants; renderVariants();
}
async function renameVariant(i, name) {
  const r = await api("/api/photos/rename", { index: i, name });
  STATE.config.variants = r.variants;
}

// ─── параметры ─────────────────────────────────────────────────────
const UNIT_MIN = { minutes: 1, hours: 60, days: 1440 };

function blockMinutesFromUI() {
  return Math.max(1, Math.round(+$("p_block_val").value)) * UNIT_MIN[$("p_block_unit").value];
}
function setBlockUI(mins) {
  mins = mins || 360;
  let unit = "minutes";
  if (mins % 1440 === 0) unit = "days";
  else if (mins % 60 === 0) unit = "hours";
  $("p_block_unit").value = unit;
  $("p_block_val").value = mins / UNIT_MIN[unit];
}
function humanDur(mins) {
  if (mins < 60) return `${mins} мин`;
  if (mins < 1440) return `${(mins/60).toFixed(mins%60?1:0)} ч`;
  return `${(mins/1440).toFixed(mins%1440?1:0)} сут`;
}

function renderParams() {
  const c = STATE.config;
  setBlockUI(c.block_minutes);
  $("p_cycles").value = c.cycles;
  $("p_settle_min").value = c.settle_minutes;
  $("p_min_impr").value = c.min_impressions_per_variant;
  $("p_shuffle").checked = !!c.shuffle_each_cycle;
  $("p_apply_winner").checked = !!c.apply_winner_on_finish;
  estimate();
}
function estimate() {
  const n = (STATE.config.variants || []).length || 5;
  const bm = blockMinutesFromUI(), cy = +$("p_cycles").value;
  const total = n * bm * cy;
  const box = $("params-msg");
  box.style.display = "block"; box.className = "msg info";
  box.textContent = `${n} вар. × ${humanDur(bm)} × ${cy} цикла = ${humanDur(total)} теста` +
    (bm < 360 ? "  ⚠ блок < 6 ч — привязка показов к варианту менее точна" : "");
}
["p_block_val","p_block_unit","p_cycles"].forEach(id => $(id).addEventListener("input", estimate));

async function saveParams() {
  const body = {
    block_minutes: blockMinutesFromUI(), cycles: +$("p_cycles").value,
    settle_minutes: +$("p_settle_min").value,
    min_impressions_per_variant: +$("p_min_impr").value,
    shuffle_each_cycle: $("p_shuffle").checked,
    apply_winner_on_finish: $("p_apply_winner").checked,
  };
  try { const r = await api("/api/config", body); STATE.config = r.config; renderParams();
    msg("params-msg", "Параметры сохранены.", "ok"); }
  catch (e) { msg("params-msg", e.message, "err"); }
}

// ─── запуск ────────────────────────────────────────────────────────
async function doInit() {
  msg("init-msg", "Отправляю фото в карточку…", "info");
  try {
    const r = await api("/api/init", {});
    msg("init-msg", r.ready ? `Все ${r.total} вариантов в карточке.` :
      `В карточке ${r.present.length}/${r.total}. Осталось модерации: ${r.missing.length}. ` +
      `Нажмите «Проверить готовность» через некоторое время.`, r.ready ? "ok" : "info");
  } catch (e) { msg("init-msg", e.message, "err"); }
}
async function checkInit() {
  try {
    const r = await api("/api/init/status", {});
    msg("init-msg", r.ready ? `Готово: все ${r.total} вариантов прошли модерацию.` :
      `В карточке ${r.present.length}/${r.total}. Ещё не проявились: ${r.missing.length}.`,
      r.ready ? "ok" : "info");
  } catch (e) { msg("init-msg", e.message, "err"); }
}
async function startTest() {
  const start = $("start_dt").value ? $("start_dt").value.replace("T", "T") : "";
  msg("run-msg", "Запускаю…", "info");
  try {
    const r = await api("/api/test/start", start ? { start } : {});
    msg("run-msg", `Тест запущен. Старт ротации: ${r.start} МСК.`, "ok");
    await loadState();
  } catch (e) { msg("run-msg", e.message, "err"); }
}
async function stopTest() {
  await api("/api/test/stop", {}); await loadState();
  msg("run-msg", "Ротация на паузе. Обложка не меняется.", "info");
}
async function resetTest() {
  if (!confirm("Сбросить тест? Дата старта, статистика и отчёт будут удалены.")) return;
  await api("/api/test/reset", {}); await loadState();
  msg("run-msg", "Тест сброшен.", "info");
}

// ─── мониторинг ────────────────────────────────────────────────────
function renderStatus() {
  const s = STATE.status;
  const phases = { not_started:"не настроен", scheduled:"ждёт старта", running:"идёт",
    finished:"завершён", paused:"пауза" };
  let head = `<span class="status ${s.phase==='running'?'ok':s.phase==='finished'?'ok':'warn'}">
    ${phases[s.phase] || s.phase}</span>`;
  if (!STATE.config.enabled && s.start) head += ` <span class="status warn">ротация на паузе</span>`;
  if (s.phase === "running") {
    head += ` <span class="status">блок ${s.block}/${s.total_blocks}, цикл ${s.cycle}</span>`;
    head += ` <span class="status">сейчас: ${s.active_variant || "?"}</span>`;
    head += s.switch_confirmed
      ? ` <span class="status ok">переключение зафиксировано</span>`
      : ` <span class="status err">переключение НЕ зафиксировано — запусти «Обновить сейчас»</span>`;
  }
  if (s.start) head += `<div class="muted" style="margin-top:8px">старт ${s.start} · конец ${s.finish || "?"}</div>`;
  if (s.error) head += `<div class="msg err" style="display:block">${s.error}</div>`;
  $("phase-box").innerHTML = head;

  if (s.schedule && s.schedule.length) {
    $("sched-box").innerHTML = `<table class="sched"><thead><tr>
      <th>блок</th><th>цикл</th><th>вариант</th><th>период (МСК)</th><th>учёт с</th></tr></thead><tbody>` +
      s.schedule.map(r => `<tr>
        <td class="${r.block+1===s.block?'cur':''}">${r.block+1}</td><td>${r.cycle+1}</td>
        <td>${r.variant_name}</td><td>${r.from} .. ${r.to}</td><td>${r.measure_from}</td></tr>`).join("") +
      `</tbody></table>`;
  } else $("sched-box").innerHTML = "";

  const sw = s.switches || [];
  $("switch-box").innerHTML = sw.length ? `<table><thead><tr><th>время (UTC)</th><th>блок</th>
    <th>вариант</th><th>сменилось</th></tr></thead><tbody>` + sw.slice().reverse().map(x =>
    `<tr><td>${x.at_utc}</td><td>${x.block+1}</td><td>#${x.variant_index}</td>
     <td>${x.changed ? "да" : "нет"}</td></tr>`).join("") + `</tbody></table>` :
    '<p class="muted">переключений ещё не было</p>';
  $("worker-log").textContent = STATE.worker_log || "(лог пуст)";
}
async function runNow() {
  msg("run-now-msg", "Выполняю ротацию и сбор статистики…", "info");
  try {
    const r = await api("/api/run-now", {});
    STATE = r.state;
    renderStatus(); renderResults();
    const st = r.summary.steps || {};
    msg("run-now-msg", "Готово. " + Object.entries(st).map(([k,v]) => `${k}: ${v}`).join(" · "), "ok");
  } catch (e) { msg("run-now-msg", e.message, "err"); }
}

// ─── результаты ────────────────────────────────────────────────────
function renderResults() {
  const res = STATE.results;
  const box = $("results-box");
  if (!res || !res.ranked || !res.ranked.length || !res.total_views) {
    box.innerHTML = '<p class="muted">Пока нет зачтённых данных. Появятся после первых полных суток блока (минус переходный период).</p>';
    return;
  }
  const max = Math.max(...res.ranked.map(v => v.ctr)) || 1;
  let html = `<p class="muted">зачтено показов ${fmt(res.total_views)}, кликов ${fmt(res.total_clicks)} ·
     обновлено ${res.updated_at || ""}</p>`;
  html += `<table><thead><tr><th>#</th><th>вариант</th><th>показы</th><th>клики</th>
     <th>CTR</th><th></th><th>заказы</th><th></th></tr></thead><tbody>`;
  res.ranked.forEach((v, i) => {
    const win = res.winner && res.winner.variant_index === v.variant_index;
    html += `<tr>
      <td>${i+1}</td>
      <td>${v.variant_name}${win ? " 🏆" : ""}</td>
      <td class="num">${fmt(v.views)}</td>
      <td class="num">${fmt(v.clicks)}</td>
      <td class="num">${pct(v.ctr)}</td>
      <td style="width:120px"><div class="bar"><i style="width:${100*v.ctr/max}%"></i></div></td>
      <td class="num">${v.orders||0}</td>
      <td><button class="ghost small" onclick="applyWinner(${v.variant_index})">сделать обложкой</button></td>
    </tr>`;
  });
  html += `</tbody></table>`;

  if (res.comparisons && res.comparisons.length) {
    html += `<table><thead><tr><th>сравнение с лидером</th><th>Δ CTR, п.п.</th><th>p-value</th><th>значимо</th></tr></thead><tbody>`;
    res.comparisons.forEach(c => {
      html += `<tr><td>${c.vs}</td><td class="num">${(100*c.diff).toFixed(2)}</td>
        <td class="num">${c.p_value.toFixed(3)}</td><td>${c.p_value < 0.05 ? "да" : "нет"}</td></tr>`;
    });
    html += `</tbody></table>`;
  }

  let verdict;
  if (res.significant && res.winner) {
    verdict = `Победитель: «${res.winner.variant_name}». Разрыв с ближайшим вариантом значим` +
      (res.consistent ? " и устойчив по циклам" : "") + ". Можно ставить эту обложку.";
  } else {
    const parts = [];
    if (!res.enough_data) parts.push("на части вариантов мало показов");
    if (res.comparisons && res.comparisons[0] && res.comparisons[0].p_value >= 0.05)
      parts.push(`разрыв лидера незначим (p=${res.comparisons[0].p_value.toFixed(3)})`);
    if (!res.consistent) parts.push("лидер меняется между циклами");
    verdict = "Вывод пока не однозначен: " + (parts.join("; ") || "недостаточно данных") + ". ";
    if (res.needed_views_per_variant)
      verdict += `Ориентир: ~${fmt(res.needed_views_per_variant)} показов на вариант для подтверждения.`;
  }
  html += `<div class="verdict">${verdict}</div>`;
  html += `<details style="margin-top:10px"><summary class="muted">полный отчёт (report.md)</summary>
    <pre class="log" style="background:#f7f7f7;color:#222">${(STATE.report_md||"").replace(/</g,"&lt;")}</pre></details>`;
  box.innerHTML = html;
}
async function applyWinner(index) {
  if (!confirm("Поставить этот вариант обложкой прямо сейчас?")) return;
  try { const r = await api("/api/apply-winner", { index });
    alert(`Обложка: «${r.applied}» ${r.changed ? "установлена" : "(уже стояла)"}`); }
  catch (e) { alert(e.message); }
}

// ─── старт ─────────────────────────────────────────────────────────
loadState().catch(e => msg("conn-msg", "Не удалось загрузить состояние: " + e.message, "err"));
setInterval(() => { if (document.visibilityState === "visible") loadState().catch(()=>{}); }, 60000);
