# Demo video script — version 3 (at most 3:00, with a live voice interaction)

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
- [ ] Check the Level 0 path once before recording: Shop 108 Machine down → Lakshmi hears Shop 112; then Machine working, Reset demo.

## Shot list

Version 3 adds the "works without a partner" path (Level 0) in the middle; the voice-over
is tighter so the whole video stays under 3:00.

| Time | Screen | Voice-over | Action (say these exact phrases) |
| --- | --- | --- | --- |
| 0:00–0:10 | Deck title slide | "80 crore Indians collect rations every month, often after hours in a queue. Ration Bolo: one phone call, by voice." | — |
| 0:10–0:18 | Simulator, banner visible | "Speech is heard by Wispr Flow" — *fallback:* "by the browser, in keyless mode" — "and our own rules decide." | Caller **Lakshmi** → **Start call**: "Card chivari ankelu 0421, sare na?" |
| 0:18–0:26 | Simulator | "Her card is confirmed by its last digits, never her name." | Tap mic, **say**: "Avunu." |
| 0:26–0:38 | Simulator | "Rice? Yes, 24 kilos for her family." | **Say**: "Maa shop ki biyyam vachaya?" |
| 0:38–0:50 | Simulator | "About 18 ahead, around 36 minutes — and the quietest times." | **Say**: "Ippudu entha mandi unnaru?" |
| 0:50–1:05 | Simulator | "She books 10:20 tomorrow; it reads it back and books only after a yes." | **Say**: "Repu poddhuna book cheyyandi." → "Avunu." |
| 1:05–1:18 | Simulator | "Short ration? A complaint with an ID, and a formal complaint text sent to her for the officials." | **Say**: "Naaku padihenu kilolu ichharu." → "Avunu." |
| 1:18–1:30 | Dealer dashboard | "When the dealer marks the machine down, every caller hears it first and booking pauses." | Click **Machine down** (badge: "back to normal in 10 min"). |
| 1:30–1:48 | Simulator, Lakshmi again | "But we don't strand her: a nearby shop under One Nation One Ration Card, with distance and wait." | Start call as Lakshmi → "Avunu" → "Maa shop ki biyyam vachaya?" → hear "Shop 112, near Saidabad bus stop, 1.2 km away, has rice and about 10 minutes' wait." → "Avunu" → best time at 112. |
| 1:48–2:08 | Simulator, caller **Ramu** (Shop 112, Level 0) | "Shop 112 has no cooperating dealer at all. Its cardholders report to each other, and public sales data fills in." | "Avunu" → "Biyyam vachaya?" (confirmed by 4 people, public data since 9:10) → "Repu book cheyyandi" (no bookings yet → best time) → "Biyyam vachindi, ikkada 12 mandi unnaru" → "Avunu" → "Avunu". |
| 2:08–2:22 | `/shop/112` page | "Every shop gets a public page for vigilance committees: status with its source, best times, complaints — no names, small counts hidden." | Open `/shop/112`, scroll once. |
| 2:22–2:35 | **Primary:** real phone call clip · **Fallback:** WhatsApp mode as Salma | "The same engine answers any basic phone…" / "…and WhatsApp voice notes, in Hindi." | **Primary:** call the Twilio number, "Avunu", "Ippudu entha mandi unnaru?" (15 s). **Fallback:** Salma, WhatsApp mode, "Kitne log hain?" |
| 2:35–2:47 | Metrics page | "We measure the pilot targets — and how much works without any partner." | Show the metrics page, both rows of tiles. |
| 2:47–2:55 | README | "Wispr Flow hears, our rules decide. One `docker compose up`, no keys, no login. Ration Bolo." | — |

The live queue moves as judges use the demo, so say "about 18". Shop 108's "Machine down"
restores itself after 10 minutes; press **Machine working** after the take anyway.

## After recording

1. Check the length is **≤ 3:00**; trim if needed.
2. Upload to **YouTube** as **Unlisted**; open the link in a private window to confirm it plays.
3. Dealer dashboard → **Reset demo** so judges start from the scripted state.
4. Rebuild the deck with the links (fails if not a YouTube link or over the PDF limits):
   `python scripts/build_deck.py --video <youtube-url> --live <live-url>`
5. Go through `docs/SUBMISSION_CHECKLIST.md` and submit early on 30 Nov.
