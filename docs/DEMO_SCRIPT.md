# Demo video script — version 2 (at most 3:00, with a live voice interaction)

**Rules (Round 2 FAQ):** YouTube only (public or **unlisted**; Vimeo and Google Drive links
are rejected), **3:00 or less**, showing the product working **with a live voice
interaction** — speaking into the mic, not only typing. Record at 1080p with system
audio so the spoken replies are heard. Total below ≈ 2:50.

Choose the path before recording:

- **Primary path (keys set on the live link):** `WISPR_API_KEY` and `SARVAM_API_KEY` are set
  on Railway and `scripts/smoke_real.py` passed. The simulator banner reads
  "Speech-to-text: Wispr Flow · reply voice: Sarvam AI Bulbul", the browser records your
  voice and sends it to the server, and replies are Sarvam audio.
- **Fallback path (keys not ready):** run locally (`docker compose up`) or on the live link
  without speech keys. The banner reads "Keyless mode: …". Speak into the mic in Chrome
  (it uses the browser's own speech recognition) and say on screen and in the voice-over
  that this is the keyless mode.

## Pre-recording checklist

- [ ] Use **Chrome** (best Telugu/Hindi recognition); close other tabs and notifications.
- [ ] Open the live link (or http://localhost:8000). The footer shows the build commit;
      it matches the latest commit on `main`.
- [ ] Dealer dashboard → **Reset demo** (no login needed). Check "18 waiting" and
      "Rice in stock", "Machine working".
- [ ] Simulator → press the mic once and **allow microphone access**; check "Speak replies
      aloud" is ticked and the system volume is up.
- [ ] Screen recorder set to 1080p **with system audio and microphone**.
- [ ] Primary path: the banner names **Wispr Flow**. Fallback path: it says **Keyless mode**.
- [ ] Phone clip (primary path only): your phone is linked to Lakshmi's card (Dealer →
      Tester tools → Link my phone), the Twilio number is saved, and the dashboard is open
      on a second screen or a phone-screen mirror. Alternatively, WhatsApp sandbox joined.
- [ ] Practise the Telugu phrases once; speak clearly, one sentence per tap of the mic.

## Shot list

| Time | Screen | Voice-over | Action (say these exact phrases) |
| --- | --- | --- | --- |
| 0:00–0:12 | Deck title slide | "80 crore Indians collect rations every month. Families wait hours and are told 'come tomorrow'. Ration Bolo fixes that with one phone call." | — |
| 0:12–0:22 | Simulator, banner visible | "This simulator is exactly what a caller hears. Speech is heard by Wispr Flow" — *fallback:* "by the browser, because this is the keyless mode" — "and every decision is made by our own rules." | Point at the banner. Caller **Lakshmi** → **Start call**. Reply plays: "Card chivari ankelu 0421, sare na?" |
| 0:22–0:32 | Simulator | "It confirms her card by the last digits, never her name." | Tap mic, **say**: "Avunu." |
| 0:32–0:47 | Simulator | "Has rice come? Yes, 24 kilos for her family of four." | Tap mic, **say**: "Maa shop ki biyyam vachaya?" |
| 0:47–1:02 | Simulator | "How many are waiting? About 18 ahead, around 36 minutes, and tomorrow's quietest slot." | Tap mic, **say**: "Ippudu entha mandi unnaru?" |
| 1:02–1:22 | Simulator | "Book tomorrow morning: it offers 10:20, reads it back and books only after a yes. Token sent by SMS." | Tap mic, **say**: "Repu poddhuna book cheyyandi." Then **say**: "Avunu." |
| 1:22–1:37 | Simulator | "Short ration? It compares with the 24 kilos due and files a complaint with an ID." | Tap mic, **say**: "Naaku padihenu kilolu ichharu." Then **say**: "Avunu." |
| 1:37–1:57 | **Primary:** phone call clip (dashboard + call audio) · **Fallback:** simulator in WhatsApp voice-note mode as Salma | "The same engine answers a real phone call on any basic phone…" / "…and WhatsApp voice notes, here in Hindi." | **Primary:** call the Twilio number, say "Avunu", "Ippudu entha mandi unnaru?" while the dashboard shows the call in the outbox/queue (15–20 s). **Fallback:** Salma, WhatsApp mode, **say**: "Kitne log hain?" |
| 1:57–2:17 | Dealer dashboard | "The dealer serves booked and walk-in families in turn — half of every slot stays for walk-ins — and updates status by voice." | Click **Serve next**. Tap the dealer mic, **say**: "Machine down." Badge shows "back to normal in 10 min". |
| 2:17–2:27 | Simulator | "Every caller hears it first, and booking pauses." | Start a call as Salma: the status is the first thing said. |
| 2:27–2:37 | Simulator | "If speech fails twice we switch engines; a third time, a keypad menu. Nobody is stranded." | Mumble twice and once more (or type "???" three times); show the big menu buttons. |
| 2:37–2:47 | Metrics page | "We track the pilot targets: wait within 20 minutes of the slot, adoption, calls finished by voice alone, complaints closed within a week." | Show the metrics page. |
| 2:47–2:55 | README / repo | "One `docker compose up`, no keys, no login. Ration Bolo." | — |

The live queue moves as judges use the demo, so say "about 18" — the exact number may differ.

## After recording

1. Check the length is **≤ 3:00**; trim if needed.
2. Upload to **YouTube** as **Unlisted**; open the link in a private window to confirm it plays.
3. Dealer dashboard → **Reset demo** so judges start from the scripted state.
4. Rebuild the deck with the links (fails if not a YouTube link or over the PDF limits):
   `python scripts/build_deck.py --video <youtube-url> --live <live-url>`
5. Go through `docs/SUBMISSION_CHECKLIST.md` and submit early on 30 Nov.
