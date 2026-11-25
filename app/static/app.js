(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);

  // ---------------- صفحهٔ ورود
  const loginErr = $("login-error");
  if (loginErr) {
    const e = new URLSearchParams(location.search).get("e");
    const msgs = {
      bad: "رمز عبور اشتباه است.",
      locked: "تعداد تلاش‌های ناموفق زیاد بود. ۱۰ دقیقه دیگر دوباره امتحان کنید.",
    };
    if (msgs[e]) { loginErr.textContent = msgs[e]; loginErr.classList.remove("hidden"); }
    return;
  }

  // ---------------- ابزارها
  function show(el, text, kind) {
    el.textContent = text;
    el.className = "alert " + (kind || "");
    el.classList.remove("hidden");
  }

  async function api(url, opts) {
    const r = await fetch(url, Object.assign({ credentials: "same-origin" }, opts || {}));
    if (r.status === 401) { location.href = "/login"; throw new Error("ابتدا وارد شوید."); }
    let data = null;
    try { data = await r.json(); } catch (_) { /* ignore */ }
    if (!r.ok) throw new Error((data && data.detail) || ("خطا " + r.status));
    return data;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const sizeText = (b) => b > 1048576 ? fa((b / 1048576).toFixed(1)) + " مگابایت" : fa(Math.max(1, Math.round(b / 1024))) + " کیلوبایت";
  const dateText = (t) => new Date(t * 1000).toLocaleString("fa-IR");
  const statusLabel = { queued: "در صف", processing: "در حال تبدیل", done: "متن آماده", error: "خطا" };
  const statusClass = { "رعایت شده": "st-ok", "رعایت نسبی": "st-part", "رعایت نشده": "st-bad", "قابل ارزیابی نیست": "st-na" };
  const scoreClass = (s) => s >= 85 ? "st-ok" : s >= 60 ? "st-part" : "st-bad";

  // ---------------- تب‌ها
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
      $("tab-" + btn.dataset.tab).classList.remove("hidden");
    });
  });

  // ---------------- تنظیمات
  let hasStandards = false;
  async function loadSettings() {
    const s = await api("/api/settings");
    $("key-status").textContent = s.has_key ? s.masked : "وارد نشده";
    $("no-key").classList.toggle("hidden", s.has_key);
    const sel = $("model");
    if (!sel.options.length) {
      Object.entries(s.models).forEach(([id, label]) => {
        const o = el("option", "", label);
        o.value = id;
        if (id === s.default_model) o.selected = true;
        sel.appendChild(o);
      });
    }
    hasStandards = s.standards.has;
    $("std-status").textContent = hasStandards
      ? s.standards.filename + " — " + fa(s.standards.chars.toLocaleString()) + " نویسه — " + dateText(s.standards.updated)
      : "بارگذاری نشده";
    const ev = $("evaluate");
    ev.disabled = !hasStandards;
    if (!hasStandards) ev.checked = false;
    else if (!ev.dataset.touched) ev.checked = true;
    $("eval-hint").textContent = hasStandards ? "" : "برای فعال شدن این گزینه، ابتدا فایل استانداردها را در «تنظیمات» بارگذاری کنید.";
    $("eval_model").value = s.eval_model || "";
  }
  $("evaluate").addEventListener("change", (e) => { e.target.dataset.touched = "1"; });

  $("settings-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("settings-msg");
    try {
      await api("/api/settings", { method: "POST", body: new FormData(ev.target) });
      $("api_key").value = "";
      await loadSettings();
      show(msg, "کلید ذخیره شد. حالا «آزمایش کلید» را بزنید.", "ok");
    } catch (e) { show(msg, e.message, "error"); }
  });

  $("test-key-btn").addEventListener("click", async () => {
    const msg = $("settings-msg");
    show(msg, "در حال بررسی...", "");
    try {
      const r = await api("/api/settings/test", { method: "POST" });
      show(msg, r.message, "ok");
    } catch (e) { show(msg, e.message, "error"); }
  });

  // ---------- استانداردها
  async function loadStandardsText() {
    try {
      const s = await api("/api/standards");
      $("std-text").value = s.text || "";
    } catch (_) { /* ignore */ }
  }

  $("std-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("std-msg");
    show(msg, "در حال بارگذاری و خواندن فایل...", "");
    try {
      const r = await api("/api/standards", { method: "POST", body: new FormData(ev.target) });
      ev.target.reset();
      $("std-text").value = r.text;
      $("std-details").open = true;
      await loadSettings();
      show(msg, "فایل استانداردها ذخیره شد (" + fa(r.chars.toLocaleString()) + " نویسه). متن استخراج‌شده را یک بار بررسی کنید.", "ok");
    } catch (e) { show(msg, e.message, "error"); }
  });

  $("std-save-btn").addEventListener("click", async () => {
    const msg = $("std-msg");
    const fd = new FormData(); fd.append("text", $("std-text").value);
    try {
      await api("/api/standards/text", { method: "POST", body: fd });
      await loadSettings();
      show(msg, "تغییرات متن استانداردها ذخیره شد.", "ok");
    } catch (e) { show(msg, e.message, "error"); }
  });

  $("std-del-btn").addEventListener("click", async () => {
    if (!confirm("استانداردهای پاسخگویی حذف شود؟ ارزیابی‌های قبلی باقی می‌مانند.")) return;
    try {
      await api("/api/standards", { method: "DELETE" });
      $("std-text").value = "";
      await loadSettings();
      show($("std-msg"), "استانداردها حذف شد.", "ok");
    } catch (e) { show($("std-msg"), e.message, "error"); }
  });

  // ---------- مدل ارزیابی
  $("evalmodel-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/settings/eval-model", { method: "POST", body: new FormData(ev.target) });
      show($("evalmodel-msg"), $("eval_model").value ? "مدل ارزیابی ذخیره شد." : "انتخاب مدل ارزیابی روی حالت خودکار قرار گرفت.", "ok");
    } catch (e) { show($("evalmodel-msg"), e.message, "error"); }
  });

  $("load-models-btn").addEventListener("click", async () => {
    const msg = $("evalmodel-msg");
    show(msg, "در حال دریافت فهرست مدل‌ها...", "");
    try {
      const r = await api("/api/eval-models");
      const dl = $("eval-model-list"); dl.innerHTML = "";
      r.models.forEach((m) => { const o = el("option"); o.value = m; dl.appendChild(o); });
      $("eval-auto").textContent = r.auto ? "در حالت خودکار این مدل استفاده می‌شود: " + r.auto : "";
      show(msg, fa(r.models.length) + " مدل در دسترس است. روی کادر «نام مدل» کلیک کنید تا فهرست را ببینید.", "ok");
    } catch (e) { show(msg, e.message, "error"); }
  });

  // ---------------- ارسال فایل‌ها (چند فایل پشت‌سرهم)
  function uploadOne(file, form, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("model", form.model.value);
      fd.append("prompt", form.prompt.value);
      fd.append("keywords", form.keywords.value);
      if (form.evaluate.checked) fd.append("evaluate", "1");
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
        if (xhr.status === 401) { location.href = "/login"; return; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.detail || ("خطا در ارسال فایل (" + xhr.status + ")")));
      };
      xhr.onerror = () => reject(new Error("ارسال فایل ناموفق بود. اتصال را بررسی کنید."));
      xhr.send(fd);
    });
  }

  $("upload-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target, btn = $("upload-btn"), msg = $("upload-msg");
    const prog = $("upload-progress"), bar = $("upload-bar");
    const files = Array.from(form.file.files);
    if (!files.length) return;
    btn.disabled = true; prog.classList.remove("hidden");
    let ok = 0; const errors = [];
    for (let i = 0; i < files.length; i++) {
      show(msg, "در حال ارسال فایل " + fa(i + 1) + " از " + fa(files.length) + ": " + files[i].name, "");
      try {
        await uploadOne(files[i], form, (p) => { bar.style.width = (100 * (i + p) / files.length) + "%"; });
        ok++; refreshJobs();
      } catch (e) { errors.push(files[i].name + ": " + e.message); }
    }
    btn.disabled = false; prog.classList.add("hidden"); bar.style.width = "0";
    form.file.value = "";
    if (errors.length) show(msg, fa(ok) + " فایل ارسال شد. خطا: " + errors.join(" | "), "error");
    else show(msg, fa(ok) + " فایل ارسال شد و در حال پردازش است. نتیجه در فهرست «تماس‌ها» نمایش داده می‌شود.", "ok");
    loadSettings(); refreshJobs();
  });

  // ---------------- فهرست تماس‌ها
  let pollTimer = null;
  let openId = null;

  function jobStatusText(j) {
    if (j.status !== "done") return statusLabel[j.status] + " — " + (j.step || "");
    if (j.eval_status === "queued" || j.eval_status === "running") return "متن آماده — " + (j.eval_step || "در حال ارزیابی...");
    if (j.eval_status === "error") return "متن آماده — ارزیابی ناموفق: " + (j.eval_step || "");
    return "آماده";
  }

  async function refreshJobs() {
    clearTimeout(pollTimer);
    let jobs = [];
    try { jobs = await api("/api/jobs"); } catch (_) { pollTimer = setTimeout(refreshJobs, 5000); return; }
    const box = $("jobs");
    box.innerHTML = "";
    if (!jobs.length) box.appendChild(el("p", "muted", "هنوز فایلی ارسال نشده است."));
    jobs.forEach((j) => {
      const row = el("div", "job");
      const info = el("div", "info");
      info.appendChild(el("div", "name", j.filename));
      const busy = j.status === "queued" || j.status === "processing" || j.eval_status === "queued" || j.eval_status === "running";
      const cls = j.status === "error" || j.eval_status === "error" ? "status-error" : busy ? "status-processing" : "status-done";
      info.appendChild(el("div", "step " + cls, jobStatusText(j)));
      info.appendChild(el("div", "muted step", sizeText(j.size) + " · " + j.model + " · " + dateText(j.created)));

      const actions = el("div", "actions");
      if (typeof j.score === "number") {
        const badge = el("span", "badge " + scoreClass(j.score), fa(j.score));
        badge.title = j.verdict || "";
        actions.appendChild(badge);
      }
      if (j.status === "done") {
        const view = el("button", "btn small", "مشاهده");
        view.onclick = () => openResult(j.id);
        actions.appendChild(view);
      }
      if (!busy) {
        const del = el("button", "btn small", "حذف");
        del.onclick = async () => {
          if (!confirm("این مورد حذف شود؟")) return;
          try { await api("/api/jobs/" + j.id, { method: "DELETE" }); } catch (e) { alert(e.message); }
          if (openId === j.id) { $("result-card").classList.add("hidden"); openId = null; }
          refreshJobs();
        };
        actions.appendChild(del);
      }
      row.append(info, actions);
      box.appendChild(row);
    });
    const anyBusy = jobs.some((j) => j.status === "queued" || j.status === "processing" || j.eval_status === "queued" || j.eval_status === "running");
    if (openId) {
      const cur = jobs.find((x) => x.id === openId);
      if (cur && cur.eval_status !== $("result-card").dataset.evalStatus) openResult(openId, true);
    }
    pollTimer = setTimeout(refreshJobs, anyBusy ? 3000 : 20000);
  }

  function fillList(id, items) {
    const ul = $(id); ul.innerHTML = "";
    (items && items.length ? items : ["—"]).forEach((t) => ul.appendChild(el("li", "", t)));
  }

  async function openResult(id, quiet) {
    const j = await api("/api/jobs/" + id);
    openId = id;
    const card = $("result-card");
    card.dataset.evalStatus = j.eval_status || "";
    $("result-title").textContent = j.filename;
    $("result-text").value = j.text || "(متنی تشخیص داده نشد)";
    $("download-btn").href = "/api/jobs/" + id + "/download";
    $("download-btn").textContent = j.evaluation ? "دانلود گزارش ارزیابی" : "دانلود متن";

    const busy = j.eval_status === "queued" || j.eval_status === "running";
    $("reeval-btn").textContent = j.evaluation ? "ارزیابی دوباره" : "ارزیابی با استانداردها";
    $("reeval-btn").disabled = busy || !hasStandards;

    const st = $("eval-status");
    if (busy) show(st, j.eval_step || "در حال ارزیابی...", "");
    else if (j.eval_status === "error") show(st, "ارزیابی ناموفق بود: " + j.eval_step, "error");
    else st.classList.add("hidden");

    const ev = j.evaluation;
    $("eval-box").classList.toggle("hidden", !ev);
    if (ev) {
      const sc = $("ev-score");
      sc.textContent = fa(ev.overall_score);
      sc.className = "score " + scoreClass(ev.overall_score);
      const vd = $("ev-verdict");
      vd.textContent = ev.verdict;
      vd.className = "verdict " + (statusClass[ev.verdict] || "");
      $("ev-meta").textContent = "استاندارد: " + (j.standards_name || "—") + " · مدل ارزیابی: " + (j.eval_model || "—") +
        (j.evaluated_at ? " · " + dateText(j.evaluated_at) : "");
      $("ev-changed").classList.toggle("hidden", !j.standards_changed);
      $("ev-summary").textContent = ev.summary || "";
      $("ev-call").textContent = ev.call_summary || "—";
      $("ev-speakers").textContent = ev.speakers || "—";

      const tb = $("ev-criteria"); tb.innerHTML = "";
      (ev.criteria || []).forEach((c, i) => {
        const tr = el("tr");
        tr.appendChild(el("td", "", fa(i + 1)));
        tr.appendChild(el("td", "", c.title));
        const tdS = el("td"); tdS.appendChild(el("span", "pill " + (statusClass[c.status] || ""), c.status)); tr.appendChild(tdS);
        const tdC = el("td");
        if (c.comment) tdC.appendChild(el("div", "", c.comment));
        if (c.evidence) tdC.appendChild(el("div", "evidence", "«" + c.evidence + "»"));
        tr.appendChild(tdC);
        tb.appendChild(tr);
      });
      fillList("ev-violations", ev.violations);
      fillList("ev-strengths", ev.strengths);
      fillList("ev-recs", ev.recommendations);
    }
    card.classList.remove("hidden");
    if (!quiet) card.scrollIntoView({ behavior: "smooth" });
  }

  $("reeval-btn").addEventListener("click", async () => {
    if (!openId) return;
    try {
      await api("/api/jobs/" + openId + "/evaluate", { method: "POST" });
      await openResult(openId, true);
      refreshJobs();
    } catch (e) { show($("eval-status"), e.message, "error"); }
  });

  $("copy-btn").addEventListener("click", async () => {
    const t = $("result-text");
    try { await navigator.clipboard.writeText(t.value); }
    catch (_) { t.select(); document.execCommand("copy"); }
    $("copy-btn").textContent = "کپی شد ✓";
    setTimeout(() => { $("copy-btn").textContent = "کپی متن"; }, 1500);
  });

  loadSettings().catch(() => {});
  loadStandardsText();
  refreshJobs();
})();
