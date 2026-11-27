# Demo video script (under 3 minutes)

Record the screen at 1080p with system audio on (so the spoken replies are heard).
Use Chrome. Before recording: `docker compose up` (or the live link), open the dealer
dashboard, log in with 1234, press **Reset demo**. Keep three tabs open: simulator,
dealer dashboard, metrics. Times are targets; total ≈ 2:50.

| Time | Screen | Say (voice-over) | Do |
| --- | --- | --- | --- |
| 0:00–0:15 | Title slide or simulator | "80 crore Indians collect rations every month. Families wait hours and are told 'come tomorrow'. Ration Bolo fixes that with one phone call — no app, no reading, no typing." | — |
| 0:15–0:25 | Simulator | "This simulator is exactly what a caller hears on a phone call. Lakshmi calls from a basic phone." | Caller Lakshmi → Start call. Reply plays: "Card chivari ankelu 0421, sare na?" |
| 0:25–0:35 | Simulator | "It confirms her card by the last four digits. It never says her name." | Mic → say "Avunu". |
| 0:35–0:50 | Simulator | "Has rice come? Yes — 24 kilos for her family of four." | Mic → "Maa shop ki biyyam vachaya?" |
| 0:50–1:05 | Simulator | "How many people are there? 18 ahead, about 36 minutes — and the quietest slot tomorrow." | Mic → "Ippudu entha mandi unnaru?" |
| 1:05–1:25 | Simulator | "Book tomorrow morning. It offers 10:20, reads it back, and books only after a yes. Token B-036, sent by SMS." | Mic → "Repu poddhuna book cheyyandi" → "Avunu". |
| 1:25–1:40 | Simulator | "Short ration? 'I got 15 kilos.' It compares with the 24 due, reads back, files complaint C-108-0003." | Mic → "Naaku 15 kilolu ichharu" → "Avunu". |
| 1:40–1:55 | Simulator, Salma, WhatsApp mode | "The same works in Hindi, and on WhatsApp voice notes." | Caller Salma, WhatsApp mode → "Kitne log hain?" |
| 1:55–2:15 | Dealer dashboard | "The dealer sees the live queue with only the last four digits, serves booked and walk-in families in turn — half of every slot stays for walk-ins — and can say 'Machine down'." | Click Serve next. Type/say "Machine down". Show the pause badge. |
| 2:15–2:25 | Simulator | "Every channel hears it first, and booking pauses." | Start a call as Salma: status is the first thing said. |
| 2:25–2:35 | Simulator | "If speech fails twice we switch engines; a third time, a keypad menu. Nobody is stranded." | Say nonsense three times; show the menu buttons. |
| 2:35–2:45 | Metrics | "We measure what matters: wait within 20 minutes of the slot, adoption, calls finished by voice alone, complaints closed within a week." | Show metrics page. |
| 2:45–2:55 | Title / README | "Wispr Flow hears, our rules decide. One `docker compose up`, no keys needed. Ration Bolo." | — |

Tips: speak replies aloud stays on. If the browser can't recognise Telugu speech, tap
the example-phrase chips — they send exactly what a caller would say. Upload to YouTube
as **Unlisted**, under 3:00, and paste the link into the deck (slide 11) and the form.
