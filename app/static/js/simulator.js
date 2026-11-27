// Ration Bolo call simulator. No build step, no libraries.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { session: null, mode: "call", status: null, listening: false, recorder: null,
                  recognition: null, browserLang: "te-IN", ended: true, packs: [] };

  const EXAMPLES = {
    te: ["Avunu", "Kaadu", "Maa shop ki biyyam vachaya?", "Ippudu entha mandi unnaru?",
         "Repu poddhuna book cheyyandi", "Naaku 15 kilolu ichharu", "Hindi lo cheppandi", "Chalu, dhanyavaadalu"],
    hi: ["Haan", "Nahi", "Mera ration aaya kya?", "Kitne log hain?", "Kal subah book karo",
         "Mujhe kam mila", "Telugu mein bolo", "Bas, dhanyavaad"],
    en: ["Yes", "No", "Has rice come?", "How many people are in the queue?", "Book tomorrow morning",
         "I got 15 kg", "Thank you, bye"],
    digits: ["1 0 8 0 4 2 1", "1 0 8 0 5 1 3", "0 6 1 0", "0 7 3 3"],
  };
  const MENU_LABELS = { stock: "Stock", queue: "Queue", book: "Book a slot", complaint: "Short ration" };

  async function api(path, body) {
    const opts = body instanceof FormData ? { method: "POST", body }
      : { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body) };
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }

  function bubble(kind, text, extra) {
    const div = document.createElement("div");
    div.className = `bubble ${kind}`;
    div.textContent = text;
    if (extra && extra.gloss && extra.gloss !== text) {
      const g = document.createElement("span"); g.className = "gloss"; g.textContent = extra.gloss; div.appendChild(g);
    }
    if (extra && extra.meta) {
      const m = document.createElement("span"); m.className = "meta"; m.textContent = extra.meta; div.appendChild(m);
    }
    if (extra && extra.replay) {
      const b = document.createElement("button"); b.type = "button"; b.className = "play";
      b.textContent = state.mode === "whatsapp" ? "▶ Voice note" : "🔊 Replay";
      b.addEventListener("click", extra.replay); div.appendChild(b);
    }
    $("log").appendChild(div);
    $("log").scrollTop = $("log").scrollHeight;
    return div;
  }

  function speak(reply) {
    if (!$("speak").checked) return;
    if (reply.audio_url) { new Audio(reply.audio_url).play().catch(() => {}); return; }
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(reply.text);
    u.lang = reply.browser_lang;
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang === reply.browser_lang)
      || window.speechSynthesis.getVoices().find((v) => v.lang.startsWith(reply.language));
    if (voice) u.voice = voice;
    u.rate = 0.95;
    window.speechSynthesis.speak(u);
  }

  function render(reply) {
    state.browserLang = reply.browser_lang;
    if (reply.heard && reply.heard.engine && reply.heard.engine !== "text" && reply.heard.engine !== "browser") {
      const heard = reply.heard.text ? `“${reply.heard.text}”` : "(nothing heard)";
      bubble("me", heard, { meta: `heard by ${reply.heard.engine}${reply.heard.error ? " · " + reply.heard.error : ""}` });
    }
    const replay = () => speak(reply);
    const said = bubble("app", reply.text, { gloss: reply.gloss, replay });
    said.lang = reply.browser_lang;  // screen readers pronounce Telugu/Hindi correctly
    const gloss = said.querySelector(".gloss"); if (gloss) gloss.lang = "en";
    for (const a of reply.actions || []) {
      const note = {
        booking_created: () => `✅ Booked token ${a.token} · ${a.date} ${a.time}`,
        booking_refused: () => `⛔ Booking refused (${a.reason})`,
        complaint_filed: () => `📝 Complaint ${a.complaint_no} filed (${a.kg_received} of ${a.kg_due} kg)`,
        engine_switched: () => "🔁 Switched to the backup speech engine",
        menu_shown: () => "🔢 Fallback menu shown",
        phone_linked: () => `🔗 This phone is now linked to card ••${a.last4}`,
        language_switched: () => `🌐 Language: ${a.language}`,
        summary_sent: () => "✉ Text summary sent (see dealer outbox)",
        call_ended: () => "Call ended",
      }[a.type];
      if (note) bubble("sys", note());
    }
    $("engine-badge").textContent = `engine: ${reply.engine === "backup" ? "backup" : "primary"}`;
    $("engine-badge").className = `badge ${reply.engine === "backup" ? "bad" : "ok"}`;
    showMenu(reply.menu);
    setChips(reply);
    speak(reply);
    if (reply.ended) finish();
  }

  function showMenu(menu) {
    const box = $("menu");
    box.innerHTML = "";
    box.hidden = !menu;
    if (!menu) return;
    for (const item of menu) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = `${item.key} · ${MENU_LABELS[item.intent] || item.intent}`;
      b.addEventListener("click", () => sendDigit(item.key));
      box.appendChild(b);
    }
  }

  function setChips(reply) {
    const box = $("chips");
    box.innerHTML = "";
    const lang = (reply.language || "te").slice(0, 2);
    const list = reply.expect === "digits" ? EXAMPLES.digits.concat(EXAMPLES[lang] || []).slice(0, 6)
      : EXAMPLES[lang] || EXAMPLES.te;
    for (const text of list) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = text;
      b.addEventListener("click", () => sendText(text, "text"));
      box.appendChild(b);
    }
  }

  function setActive(on) {
    state.ended = !on;
    for (const id of ["mic", "textbox", "send", "toggle-keypad", "silence", "hangup"]) $(id).disabled = !on;
    $("start").disabled = on;
    $("caller").disabled = on; $("state").disabled = on;
    $("mode-call").disabled = on; $("mode-wa").disabled = on;
  }

  function finish() {
    stopListening();
    setActive(false);
    $("meta").textContent = "Call ended · press Start call to call again";
    $("chips").innerHTML = "";
  }

  async function startCall() {
    $("log").innerHTML = "";
    const callerSel = $("caller");
    try {
      const reply = await api("/api/sim/start", { caller: callerSel.value, state: $("state").value, mode: state.mode });
      state.session = reply.session_id;
      setActive(true);
      $("who").textContent = callerSel.options[callerSel.selectedIndex].text;
      $("meta").textContent = state.mode === "whatsapp" ? "WhatsApp chat · voice notes" : "On call · Ration Bolo";
      bubble("sys", state.mode === "whatsapp" ? "WhatsApp chat started" : "Calling Ration Bolo…");
      render(reply);
    } catch (e) { bubble("sys", `Could not start: ${e.message}`); }
  }

  async function sendText(text, engine) {
    if (!state.session || state.ended || !text.trim()) return;
    bubble("me", text, { meta: engine === "browser" ? "heard by browser speech" : "typed" });
    try { render(await api(`/api/sim/${state.session}/text`, { text, engine })); }
    catch (e) { bubble("sys", `Error: ${e.message}`); }
  }

  async function sendDigit(key) {
    if (!state.session || state.ended) return;
    bubble("me", `⌨ ${key}`, { meta: "keypad" });
    try { render(await api(`/api/sim/${state.session}/digit`, { key })); }
    catch (e) { bubble("sys", `Error: ${e.message}`); }
  }

  async function sendSilence() {
    if (!state.session || state.ended) return;
    bubble("sys", "(8 seconds of silence)");
    render(await api(`/api/sim/${state.session}/silence`, {}));
  }

  async function hangUp() {
    if (!state.session || state.ended) return;
    render(await api(`/api/sim/${state.session}/end`, {}));
  }

  // --- Voice input: server speech engine if configured, else the browser's own. ---
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  function useServerSpeech() {
    return state.status && state.status.server_speech_to_text && navigator.mediaDevices && window.MediaRecorder;
  }

  async function startListening() {
    if (state.listening) { stopListening(); return; }
    window.speechSynthesis && window.speechSynthesis.cancel();
    if (useServerSpeech()) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const rec = new MediaRecorder(stream);
        const chunks = [];
        rec.ondataavailable = (e) => chunks.push(e.data);
        rec.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
          const form = new FormData(); form.append("file", blob, "speech.webm");
          try { render(await api(`/api/sim/${state.session}/audio`, form)); }
          catch (e) { bubble("sys", `Error: ${e.message}`); }
        };
        state.recorder = rec; rec.start(); setListening(true, "Listening… tap again to send");
        setTimeout(() => { if (state.recorder === rec && rec.state === "recording") stopListening(); }, 15000);
      } catch (e) { bubble("sys", "Microphone not available: type instead."); }
      return;
    }
    if (!Recognition) {
      bubble("sys", "This browser has no speech recognition. Type what you would say, or use the example phrases.");
      $("textbox").focus(); return;
    }
    const r = new Recognition();
    r.lang = state.browserLang; r.interimResults = false; r.maxAlternatives = 1;
    let got = false;
    r.onresult = (e) => { got = true; sendText(e.results[0][0].transcript, "browser"); };
    r.onerror = (e) => { if (e.error === "no-speech") { got = true; sendSilence(); } else bubble("sys", `Speech recognition: ${e.error}. Type instead.`); };
    r.onend = () => { setListening(false); if (!got) { /* nothing heard */ } };
    state.recognition = r; r.start(); setListening(true, `Listening (${state.browserLang})…`);
  }

  function stopListening() {
    if (state.recorder && state.recorder.state === "recording") state.recorder.stop();
    if (state.recognition) { try { state.recognition.stop(); } catch (e) { /* ignore */ } }
    state.recorder = null; state.recognition = null; setListening(false);
  }

  function setListening(on, hint) {
    state.listening = on;
    $("mic").classList.toggle("listening", on);
    $("mic").setAttribute("aria-label", on ? "Stop and send" : "Tap to speak");
    $("mic-hint").textContent = hint || "Tap the mic and speak, or type below.";
  }

  // --- Setup ---
  function buildKeypad() {
    const pad = $("keypad");
    for (const k of ["1","2","3","4","5","6","7","8","9","*","0","#"]) {
      const b = document.createElement("button"); b.type = "button"; b.textContent = k;
      b.setAttribute("aria-label", `Key ${k}`);
      b.addEventListener("click", () => sendDigit(k));
      pad.appendChild(b);
    }
  }

  function setMode(mode) {
    state.mode = mode;
    $("mode-call").setAttribute("aria-pressed", String(mode === "call"));
    $("mode-wa").setAttribute("aria-pressed", String(mode === "whatsapp"));
    $("phone").classList.toggle("wa", mode === "whatsapp");
    $("start").textContent = mode === "whatsapp" ? "Open WhatsApp chat" : "Start call";
  }

  async function loadStatus() {
    try {
      const s = await api("/api/status");
      state.status = s;
      const missing = s.missing_keys.length;
      $("status-summary").textContent = s.server_speech_to_text
        ? "Server speech engines active · " + (missing ? `${missing} keys not set` : "all keys set")
        : "No speech keys set: using your browser's speech recognition and voice (key not set)";
      const list = $("status-list"); list.innerHTML = "";
      for (const svc of s.services) {
        const li = document.createElement("li");
        li.textContent = `${svc.provider}: ${svc.note}`; list.appendChild(li);
      }
      for (const [name, ch] of Object.entries(s.channels)) {
        const li = document.createElement("li"); li.textContent = `Channel ${name}: ${ch.ready ? "ready" : ch.note}`; list.appendChild(li);
      }
    } catch (e) { $("status-summary").textContent = "Status unavailable"; }
  }

  async function init() {
    buildKeypad();
    const [callers, packs] = await Promise.all([api("/api/sim/callers"), api("/api/packs")]);
    for (const c of callers) { const o = new Option(c.label, c.id); $("caller").add(o); }
    for (const p of packs) { const o = new Option(p.name + (p.draft ? " (draft)" : ""), p.state); $("state").add(o); }
    $("start").addEventListener("click", startCall);
    $("hangup").addEventListener("click", hangUp);
    $("mic").addEventListener("click", startListening);
    $("silence").addEventListener("click", sendSilence);
    $("mode-call").addEventListener("click", () => setMode("call"));
    $("mode-wa").addEventListener("click", () => setMode("whatsapp"));
    $("toggle-keypad").addEventListener("click", () => { $("keypad").hidden = !$("keypad").hidden; });
    $("textform").addEventListener("submit", (e) => {
      e.preventDefault(); const t = $("textbox").value; $("textbox").value = ""; sendText(t, "text");
    });
    if ("speechSynthesis" in window) window.speechSynthesis.getVoices();
    await loadStatus();
  }
  init();
})();
