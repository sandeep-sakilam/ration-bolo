// Ration Bolo dealer dashboard.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let pin = "";
  try { pin = sessionStorage.getItem("dealerPin") || ""; } catch (e) { /* storage blocked */ }
  let timer = null;
  const volunteerId = new URLSearchParams(location.search).get("volunteer") || "";
  let shop = "";
  try { shop = sessionStorage.getItem("dealerShop") || ""; } catch (e) { /* storage blocked */ }

  async function api(path, body, isForm) {
    const opts = { method: body === undefined ? "GET" : "POST", headers: { "X-Dealer-Pin": pin, "X-Shop-Code": shop } };
    if (volunteerId) opts.headers["X-Volunteer-Id"] = volunteerId;
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    const res = await fetch("/api/dealer" + path, opts);
    if (res.status === 401) { logout(pin ? "Wrong PIN" : ""); throw new Error("unauthorised"); }
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  function flash(msg) {
    const f = $("flash"); f.textContent = msg; f.hidden = false;
    clearTimeout(flash.t); flash.t = setTimeout(() => { f.hidden = true; }, 5000);
  }

  function cell(tr, text) { const td = document.createElement("td"); td.textContent = text; tr.appendChild(td); return td; }
  function btn(td, label, fn, cls) {
    const b = document.createElement("button"); b.type = "button"; b.textContent = label;
    if (cls) b.className = cls; b.style.marginRight = "4px"; b.style.padding = "4px 8px";
    b.addEventListener("click", fn); td.appendChild(b); return b;
  }

  function render(d) {
    const v = d.volunteer;
    if (volunteerId && v) {
      shop = v.shop;
      $("volunteer-bar").hidden = false;
      $("volunteer-text").textContent = `Volunteer mode · ${v.label} · Shop ${v.shop} · ${v.on_duty ? "on duty: bookings are offered" : "off duty: the shop is Level 0"}`;
      $("duty").textContent = v.on_duty ? "Go off duty" : "Go on duty";
      $("duty").dataset.on = v.on_duty ? "1" : "";
      for (const id of ["reset", "link-form", "serve-kg", "shop-select"]) { const el = $(id); if (el) el.hidden = true; }
    }
    const ss = $("shop-select");
    if (ss.options.length !== d.shops.length) {
      ss.innerHTML = "";
      for (const s of d.shops) ss.add(new Option(`Shop ${s.code} · ${s.area}`, s.code));
    }
    ss.value = d.shop.code;
    $("shop-name").textContent = `${d.shop.name} (Shop ${d.shop.code})`;
    $("shop-area").textContent = d.shop.area;
    $("today").textContent = `Today ${d.today} · ${d.shop.families_per_hour} families an hour`;
    const stockOk = d.shop.stock === "in_stock", machineOk = d.shop.machine === "working";
    $("stock-badge").textContent = stockOk ? "Rice in stock" : "Rice finished";
    $("stock-badge").className = "badge " + (stockOk ? "ok" : "bad");
    $("machine-badge").textContent = machineOk ? "Machine working" : "Machine down";
    $("machine-badge").className = "badge " + (machineOk ? "ok" : "bad");
    const back = d.restore_in_minutes || {};
    if (back.stock) $("stock-badge").textContent += ` · back to normal in ${back.stock} min`;
    if (back.machine) $("machine-badge").textContent += ` · back to normal in ${back.machine} min`;
    $("pause-badge").hidden = !d.shop.paused;
    $("level-badge").textContent = d.level_label || "";
    const dis = d.disagreements || [];
    $("disagree").hidden = !dis.length;
    $("disagree").textContent = dis.length ? `Sources disagree: ${dis.join(" · ")}` : "";
    const rc = d.reports_3h || {};
    const parts = Object.entries(rc).map(([k, n]) => `${n} ${k.replace("_", " ")}`);
    $("reports-line").textContent = parts.length ? `Cardholder reports, last 3 hours: ${parts.join(", ")}` : "No cardholder reports in the last 3 hours."; $("pause-badge").className = "badge bad";
    $("k-waiting").textContent = d.waiting;
    $("k-wait").textContent = d.wait_minutes;
    $("k-bookings").textContent = d.bookings.filter((b) => b.status !== "cancelled").length;
    $("k-complaints").textContent = d.complaints.filter((c) => c.status === "open").length;

    const qb = $("queue-body"); qb.innerHTML = "";
    d.queue.forEach((t, i) => {
      const tr = document.createElement("tr");
      cell(tr, i + 1); cell(tr, t.token); cell(tr, t.kind === "booked" ? `booked ${t.window}` : "walk-in");
      cell(tr, `••${t.last4}`); cell(tr, t.issued); qb.appendChild(tr);
    });
    $("queue-empty").hidden = d.queue.length > 0;

    const bb = $("bookings-body"); bb.innerHTML = "";
    for (const b of d.bookings) {
      const tr = document.createElement("tr");
      cell(tr, b.date === d.today ? "Today" : "Tomorrow"); cell(tr, b.window); cell(tr, b.token);
      cell(tr, `••${b.last4}`); cell(tr, b.status);
      const td = cell(tr, "");
      if (b.status === "booked" && b.date === d.today) {
        btn(td, "Mark arrived", () => act("/arrive", { token_id: b.id }));
        btn(td, "+11 min (late)", () => act("/arrive", { token_id: b.id, minutes_after_start: 11 }));
      }
      bb.appendChild(tr);
    }

    const cb = $("complaints-body"); cb.innerHTML = "";
    for (const c of d.complaints) {
      const tr = document.createElement("tr");
      cell(tr, c.complaint_no); cell(tr, `••${c.last4}`); cell(tr, `${c.kg_due} / ${c.kg_received} kg`);
      cell(tr, c.status + (c.stage ? ` · ${c.stage}` : "") + (c.outcome ? ` · ${c.outcome}` : ""));
      const td = cell(tr, "");
      if (c.status === "open" && !volunteerId) btn(td, "Resolve", () => {
        const outcome = prompt("Outcome (e.g. 'Gave the missing rice')", "Gave the missing rice");
        if (outcome) act(`/complaints/${c.id}/resolve`, { outcome });
      });
      cb.appendChild(tr);
    }

    const ob = $("outbox-body"); ob.innerHTML = "";
    for (const o of d.outbox) {
      const tr = document.createElement("tr");
      cell(tr, `${o.at} · ${o.channel}`); cell(tr, o.to); cell(tr, `${o.body} (${o.status})`); ob.appendChild(tr);
    }

    if (d.reminders) {
      $("reminders-card").hidden = false;
      const rb = $("reminders-body"); rb.innerHTML = "";
      for (const r of d.reminders) {
        const tr = document.createElement("tr");
        cell(tr, r.token); cell(tr, r.due); cell(tr, r.status);
        const td = cell(tr, "");
        if (r.status === "pending") btn(td, "Send reminder now", () => act("/reminders/send-now", { reminder_id: r.id }));
        rb.appendChild(tr);
      }
    }

    const sel = $("link-card");
    if (sel.dataset.shop !== d.shop.code) { sel.innerHTML = ""; sel.dataset.shop = d.shop.code; }
    if (!sel.options.length) for (const c of d.demo_cards) sel.add(new Option(`${c.label} · ••${c.last4}`, c.id));
  }

  async function refresh() { try { render(await api("/overview")); } catch (e) { /* shown elsewhere */ } }

  async function act(path, body) {
    try { const r = await api(path, body); if (r.message) flash(r.message); await refresh(); return r; }
    catch (e) { flash(`Error: ${e.message}`); return null; }
  }

  function logout(msg) {
    pin = ""; try { sessionStorage.removeItem("dealerPin"); } catch (e) { /* ignore */ }
    $("dash").hidden = true; $("login").hidden = false;
    $("login-error").textContent = msg || ""; clearInterval(timer);
  }

  async function login() {
    try {
      render(await api("/overview"));
      try { sessionStorage.setItem("dealerPin", pin); } catch (e) { /* ignore */ }
      $("login").hidden = true; $("dash").hidden = false; $("logout").hidden = !pin;
      clearInterval(timer); timer = setInterval(refresh, 5000);
    } catch (e) { if (pin) $("login-error").textContent = "Wrong PIN"; }
  }

  // Voice status updates: server engine if configured, else the browser's recognition.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  function voice() {
    if (!Recognition) { flash("No speech recognition in this browser: type the phrase instead."); $("voice-text").focus(); return; }
    const r = new Recognition(); r.lang = "te-IN"; r.interimResults = false;
    $("dealer-mic").classList.add("listening");
    r.onresult = (e) => sendVoice(e.results[0][0].transcript);
    r.onend = () => $("dealer-mic").classList.remove("listening");
    r.onerror = (e) => flash(`Speech recognition: ${e.error}`);
    r.start();
  }
  async function sendVoice(text) { const r = await act("/voice", { text }); if (r) flash(`Heard “${r.heard}”: ${r.message}`); }

  $("shop-select").addEventListener("change", (e) => {
    shop = e.target.value;
    try { sessionStorage.setItem("dealerShop", shop); } catch (err) { /* ignore */ }
    refresh();
  });
  $("login-form").addEventListener("submit", (e) => { e.preventDefault(); pin = $("pin").value; login(); });
  $("serve").addEventListener("click", () => {
    const kg = $("serve-kg").value; $("serve-kg").value = "";
    act("/serve", kg === "" ? {} : { kg: Number(kg) });
  });
  $("walkin").addEventListener("click", () => act("/walkin", {}));
  $("duty").addEventListener("click", () => act("/volunteer/duty", { on_duty: !$("duty").dataset.on }));
  $("stock-out").addEventListener("click", () => act("/status", { stock: "out" }).then(() => flash("Rice finished: booking paused on every channel")));
  $("stock-in").addEventListener("click", () => act("/status", { stock: "in_stock" }).then(() => flash("Rice in stock")));
  $("machine-down").addEventListener("click", () => act("/status", { machine: "down" }).then(() => flash("Machine down: booking paused on every channel")));
  $("machine-up").addEventListener("click", () => act("/status", { machine: "working" }).then(() => flash("Machine working")));
  $("dealer-mic").addEventListener("click", voice);
  $("voice-form").addEventListener("submit", (e) => { e.preventDefault(); const t = $("voice-text").value; $("voice-text").value = ""; if (t) sendVoice(t); });
  $("link-form").addEventListener("submit", (e) => {
    e.preventDefault(); act("/link-phone", { phone: $("link-phone").value, card_id: Number($("link-card").value) });
  });
  $("reset").addEventListener("click", () => { if (confirm("Restore the demo data? Bookings and complaints made in the demo are removed.")) act("/reset", {}); });
  $("logout").addEventListener("click", () => logout());
  login();  // opens straight away when the server has no PIN set (no login wall)
})();
