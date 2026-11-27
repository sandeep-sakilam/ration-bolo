(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
  const num = (v, unit) => (v === null || v === undefined ? "–" : `${v}${unit || ""}`);

  function kpi(value, label, target, ok) {
    const div = document.createElement("div"); div.className = "card kpi";
    div.innerHTML = '<div class="value"></div><div class="label"></div><div class="target"></div>';
    div.querySelector(".value").textContent = value;
    div.querySelector(".label").textContent = label;
    const t = div.querySelector(".target"); t.textContent = target || "";
    if (ok !== undefined) t.className = "target " + (ok ? "good" : "short");
    return div;
  }

  function bar(label, parts, total, right) {
    const row = document.createElement("div"); row.className = "bar";
    const l = document.createElement("span"); l.textContent = label;
    const track = document.createElement("div"); track.className = "track";
    for (const [value, cls] of parts) {
      const f = document.createElement("div"); f.className = "fill " + (cls || "");
      f.style.width = total ? `${(100 * value) / total}%` : "0"; track.appendChild(f);
    }
    const r = document.createElement("span"); r.textContent = right;
    row.append(l, track, r); return row;
  }

  async function load() {
    const days = $("range").value;
    const m = await (await fetch(`/api/metrics?days=${days}`)).json();
    $("days").textContent = m.days;
    const T = m.targets, k = $("kpis"); k.innerHTML = "";
    k.append(
      kpi(num(m.wait.booked_avg_minutes, " min"), "average wait with a booking",
          `walk-ins: ${num(m.wait.walkin_avg_minutes, " min")}`),
      kpi(pct(m.wait.booked_within_20_min), "booked families served within 20 min of slot",
          `target ${pct(T.booked_within_20_min)}`, m.wait.booked_within_20_min >= T.booked_within_20_min),
      kpi(pct(m.bookings.adoption), "of families served came with a booking",
          `target ${pct(T.adoption)} by month 3`, m.bookings.adoption >= T.adoption),
      kpi(pct(m.voice.voice_success), "of calls finished by voice alone (no menu)",
          `target ${pct(T.voice_success)}`, m.voice.voice_success >= T.voice_success),
      kpi(num(m.bookings.made), "bookings made", `${m.bookings.late_or_no_show} late or no-show`),
      kpi(num(m.bookings.status_checks_by_phone), "stock/queue checks by phone", "trips not wasted"),
      kpi(pct(m.complaints.resolved_7_days), "complaints resolved within 7 days",
          `${m.complaints.open} open · ${m.complaints.overdue} overdue · target 100%`,
          m.complaints.resolved_7_days === null || m.complaints.resolved_7_days >= T.complaints_resolved_7_days),
      kpi(pct(m.voice.backup_engine_sessions), "of calls switched to the backup engine",
          `${pct(m.voice.understood_turns)} of turns understood`),
    );
    const p = m.without_partner, pk = $("partner"); pk.innerHTML = "";
    if (p) {
      const L = p.shops_by_level;
      pk.append(
        kpi(`${L[0]} · ${L[1]} · ${L[2]}`, "shops at Level 0 · 1 · 2", "Level 0 = nobody cooperates"),
        kpi(num(p.cardholder_reports), "cardholder reports", `${p.reporters} different phones · ${p.check_ins} check-ins`),
        kpi(`${p.nearby_accepted} / ${p.nearby_offered}`, "nearby-shop suggestions taken", "One Nation One Ration Card"),
        kpi(num(p.rice_arrived_messages), "\"rice arrived\" messages", "to opted-in cardholders"),
        kpi(num(p.complaints_routed), "complaints routed to officials", `${p.complaints_escalated} escalated · ${p.references_recorded} official references`),
      );
    }
    const d = $("daily"); d.innerHTML = "";
    const max = Math.max(1, ...m.daily.map((x) => x.served));
    for (const x of m.daily) {
      d.appendChild(bar(x.day.slice(5), [[x.booked, ""], [x.served - x.booked, "walk"]], max,
        `${x.served} · ${num(x.avg_wait, "m")}`));
    }
    if (!m.daily.length) d.textContent = "Nobody served in this period yet.";
    const e = $("engines"); e.innerHTML = "";
    const totalTurns = Object.values(m.voice.engines).reduce((a, b) => a + b, 0);
    for (const [name, count] of Object.entries(m.voice.engines)) {
      e.appendChild(bar(name, [[count, ""]], totalTurns, `${count}`));
    }
    $("engine-note").textContent = `${m.voice.sessions} calls and chats in this period.`;
  }
  $("range").addEventListener("change", load);
  load();
})();
