(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let pin = "";
  try { pin = sessionStorage.getItem("adminPin") || ""; } catch (e) { /* storage blocked */ }

  async function api(path, body, json) {
    const headers = { "X-Admin-Pin": pin };
    if (json) headers["Content-Type"] = "application/json";
    const opts = { method: body ? "POST" : "GET", headers, body };
    const res = await fetch("/api/admin" + path, opts);
    if (res.status === 401) { $("dash").hidden = true; $("login").hidden = false; throw new Error("Wrong PIN"); }
    const text = await res.text();
    let data; try { data = JSON.parse(text); } catch (e) { data = text; }
    if (!res.ok) { const err = new Error("request failed"); err.data = data; throw err; }
    return data;
  }

  function flash(msg) { const f = $("flash"); f.textContent = msg; f.hidden = false; }

  async function load() {
    const shops = await api("/shops");
    const body = $("shops-body"); body.innerHTML = "";
    for (const s of shops) {
      const tr = document.createElement("tr");
      for (const v of [s.code, `${s.name} · ${s.area}`]) {
        const td = document.createElement("td"); td.textContent = v; tr.appendChild(td);
      }
      const lvl = document.createElement("select");
      lvl.setAttribute("aria-label", `Level of shop ${s.code}`);
      for (const n of [0, 1, 2]) lvl.add(new Option(`Level ${n}`, String(n)));
      lvl.value = String(s.base_level);
      lvl.addEventListener("change", async () => {
        try {
          const r = await api(`/shops/${s.code}/profile`, JSON.stringify({ level: Number(lvl.value) }), true);
          flash(r.message); await load();
        } catch (e) { flash("Could not change the level"); }
      });
      const ltd = document.createElement("td"); ltd.appendChild(lvl);
      if (s.level !== s.base_level) ltd.append(` (now ${s.level})`);
      tr.appendChild(ltd);
      for (const v of [s.state_pack, s.sessions,
        `${s.stock === "in_stock" ? "rice in stock" : "rice finished"}, machine ${s.machine}`,
        s.cards, s.waiting, s.upcoming_bookings, s.open_complaints]) {
        const td = document.createElement("td"); td.textContent = v; tr.appendChild(td);
      }
      const pub = document.createElement("td");
      const month = new Date().toISOString().slice(0, 7);
      pub.innerHTML = "";
      const a1 = document.createElement("a"); a1.href = `/shop/${s.code}`; a1.textContent = "Page";
      const a2 = document.createElement("a"); a2.href = `/shop/${s.code}/report/${month}.csv`; a2.textContent = "Monthly CSV";
      pub.append(a1, " · ", a2); tr.appendChild(pub);
      body.appendChild(tr);
    }
  }

  async function upload(kind, input) {
    const form = new FormData(); form.append("file", input.files[0]);
    $("errors").innerHTML = "";
    try {
      const r = await api(`/import/${kind}`, form);
      flash(r.message); input.value = ""; await load();
    } catch (e) {
      const detail = e.data && e.data.detail;
      flash(detail && detail.message ? `Import failed: ${detail.message}` : `Import failed: ${detail || e.message}`);
      for (const line of (detail && detail.errors) || []) {
        const li = document.createElement("li"); li.textContent = line; $("errors").appendChild(li);
      }
    }
  }

  async function template(kind) {
    const csv = await api(`/templates/${kind}.csv`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${kind}-template.csv`; a.click();
  }

  async function login() {
    try {
      await load();
      try { sessionStorage.setItem("adminPin", pin); } catch (e) { /* ignore */ }
      $("login").hidden = true; $("dash").hidden = false;
    } catch (e) { if (pin) $("login-error").textContent = "Wrong PIN"; }
  }

  $("login-form").addEventListener("submit", (e) => { e.preventDefault(); pin = $("pin").value; login(); });
  $("shops-form").addEventListener("submit", (e) => { e.preventDefault(); upload("shops", $("shops-file")); });
  $("cards-form").addEventListener("submit", (e) => { e.preventDefault(); upload("cards", $("cards-file")); });
  $("tpl-shops").addEventListener("click", (e) => { e.preventDefault(); template("shops"); });
  $("tpl-cards").addEventListener("click", (e) => { e.preventDefault(); template("cards"); });
  login();  // opens straight away when the server has no PIN set (no login wall)
})();
