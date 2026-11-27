# Ration Bolo

Voice-first ration shop assistant: ration cardholders check stock, hear the live queue, book a time slot and report short rations **by speaking**, on a phone call or a WhatsApp voice note. Built for the Scaler × Wispr Flow "Build for Bharat" hackathon, Round 2.

See `SPEC.md` for the full specification and `PROGRESS.md` for build status.

## What Sandeep must provide

- API keys: Wispr Flow API, Sarvam AI.
- Twilio: account top-up (leave trial mode), buy a US local voice number, enable India in voice geographic permissions, join the WhatsApp sandbox, set the webhook URLs.
- Railway: account, project from the GitHub repo, PostgreSQL service, environment variables, public domain.
- GitHub settings: keep the repo public, allow direct pushes to `main`, turn off the email-privacy push block, verify the email on the account.
- Checking the Telugu and Hindi phrases in the state pack with native speakers.
- Recording and uploading the demo video, exporting the final deck PDF, and the hackathon submission itself.

## State packs

Each state is one JSON file in `packs/` (languages, keywords, number words, reply phrases, entitlement per person), validated against `packs/schema.json` at startup. A broken pack stops the app with a clear error. Adding a state means adding a file.
