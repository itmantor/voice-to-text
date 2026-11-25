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

  const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const sizeText = (b) => b > 1048576 ? fa((b / 1048576).toFixed(1)) + " مگابایت" : fa(Math.max(1, Math.round(b / 1024))) + " کیلوبایت";
  const dateText = (t) => new Date(t * 1000).toLocaleString("fa-IR");
  const statusLabel = { queued: "در صف", processing: "در حال پردازش", done: "آماده", error: "خطا" };

  // ---------------- تب‌ها
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
      $("tab-" + btn.dataset.tab).classList.remove("hidden");
    });
  });

  // ---------------- تنظیمات
  async function loadSettings() {
    const s = await api("/api/settings");
    $("key-status").textContent = s.has_key ? s.masked : "وارد نشده";
    $("no-key").classList.toggle("hidden", s.has_key);
    const sel = $("model");
    if (!sel.options.length) {
      Object.entries(s.models).forEach(([id, label]) => {
        const o = document.createElement("option");
        o.value = id; o.textContent = label;
        if (id === s.default_model) o.selected = true;
        sel.appendChild(o);
      });
    }
  }

  $("settings-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("settings-msg");
    try {
      await api("/api/settings", { method: "POST", body: new FormData(ev.target) });
      $("api_key").value = "";
      await loadSettings();
      show(msg, "کلید ذخیره شد.", "ok");
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

  // ---------------- ارسال فایل
  $("upload-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const form = ev.target, btn = $("upload-btn"), msg = $("upload-msg");
    const prog = $("upload-progress"), bar = $("upload-bar");
    btn.disabled = true; msg.classList.add("hidden");
    prog.classList.remove("hidden"); bar.style.width = "0";

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.style.width = (100 * e.loaded / e.total) + "%"; };
    xhr.onload = () => {
      btn.disabled = false; prog.classList.add("hidden");
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
      if (xhr.status === 401) { location.href = "/login"; return; }
      if (xhr.status >= 200 && xhr.status < 300) {
        show(msg, "فایل ارسال شد و در حال تبدیل است. نتیجه در فهرست پایین نمایش داده می‌شود.", "ok");
        form.reset(); loadSettings(); refreshJobs();
      } else {
        show(msg, data.detail || ("خطا در ارسال فایل (" + xhr.status + ")"), "error");
      }
    };
    xhr.onerror = () => { btn.disabled = false; prog.classList.add("hidden"); show(msg, "ارسال فایل ناموفق بود. اتصال را بررسی کنید.", "error"); };
    xhr.send(new FormData(form));
  });

  // ---------------- فهرست فایل‌ها
  let pollTimer = null;
  async function refreshJobs() {
    clearTimeout(pollTimer);
    let jobs = [];
    try { jobs = await api("/api/jobs"); } catch (_) { pollTimer = setTimeout(refreshJobs, 5000); return; }
    const box = $("jobs");
    box.innerHTML = "";
    if (!jobs.length) {
      const p = document.createElement("p"); p.className = "muted"; p.textContent = "هنوز فایلی ارسال نشده است.";
      box.appendChild(p);
    }
    jobs.forEach((j) => {
      const row = document.createElement("div"); row.className = "job";
      const info = document.createElement("div");
      const name = document.createElement("div"); name.className = "name"; name.textContent = j.filename;
      const step = document.createElement("div"); step.className = "step status-" + j.status;
      step.textContent = statusLabel[j.status] + (j.status === "done" ? "" : " — " + j.step);
      const meta = document.createElement("div"); meta.className = "muted step";
      meta.textContent = sizeText(j.size) + " · " + j.model + " · " + dateText(j.created);
      info.append(name, step, meta);

      const actions = document.createElement("div"); actions.className = "actions";
      if (j.status === "done") {
        const view = document.createElement("button"); view.className = "btn small"; view.textContent = "نمایش متن";
        view.onclick = () => openResult(j.id);
        actions.appendChild(view);
      }
      if (j.status === "done" || j.status === "error") {
        const del = document.createElement("button"); del.className = "btn small"; del.textContent = "حذف";
        del.onclick = async () => {
          if (!confirm("این مورد حذف شود؟")) return;
          try { await api("/api/jobs/" + j.id, { method: "DELETE" }); } catch (e) { alert(e.message); }
          refreshJobs();
        };
        actions.appendChild(del);
      }
      row.append(info, actions);
      box.appendChild(row);
    });
    const busy = jobs.some((j) => j.status === "queued" || j.status === "processing");
    pollTimer = setTimeout(refreshJobs, busy ? 3000 : 20000);
  }

  async function openResult(id) {
    const j = await api("/api/jobs/" + id);
    $("result-title").textContent = "متن: " + j.filename;
    $("result-text").value = j.text || "(متنی تشخیص داده نشد)";
    $("download-btn").href = "/api/jobs/" + id + "/download";
    $("result-card").classList.remove("hidden");
    $("result-card").scrollIntoView({ behavior: "smooth" });
  }

  $("copy-btn").addEventListener("click", async () => {
    const t = $("result-text");
    try { await navigator.clipboard.writeText(t.value); }
    catch (_) { t.select(); document.execCommand("copy"); }
    $("copy-btn").textContent = "کپی شد ✓";
    setTimeout(() => { $("copy-btn").textContent = "کپی متن"; }, 1500);
  });

  loadSettings().catch(() => {});
  refreshJobs();
})();
