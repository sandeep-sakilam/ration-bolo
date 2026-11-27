"""SPEC "Done when" checks, driven through the real pages in a browser.

The text box stands in for speech (it is what the browser's speech recognition fills).
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


def start(page: Page, caller: str, mode: str = "call") -> None:
    page.goto("/simulator")
    page.select_option("#caller", caller)
    if mode == "whatsapp":
        page.click("#mode-wa")
    page.click("#start")
    expect(page.locator("#hangup")).to_be_enabled()


def say(page: Page, text: str, expect_text: str) -> None:
    count = page.locator("#log .bubble.app").count()
    page.fill("#textbox", text)
    page.click("#send")
    expect(page.locator("#log .bubble.app")).to_have_count(count + 1)
    expect(page.locator("#log .bubble.app").last).to_contain_text(expect_text)


def dealer(page: Page) -> None:
    page.goto("/dealer")
    expect(page.locator("#dash")).to_be_visible()


def test_check2_lakshmi_books_by_speech(page: Page, reset: None) -> None:
    start(page, "lakshmi")
    expect(page.locator("#log .bubble.app").first).to_contain_text(
        "Card chivari ankelu 0421, sare na?"
    )
    say(page, "Avunu", "Meeku ela sahayam cheyali?")
    say(page, "Maa shop ki biyyam vachaya?", "Mee kutumbaniki 24 kilolu.")
    say(page, "Ippudu entha mandi unnaru?", "18 mandi mundu unnaru, sumaru 36 nimishalu.")
    say(page, "Repu poddhuna book cheyyandi.", "Repu 10:20 ki, sare na?")
    say(page, "Avunu", "Booking ayindi. Mee token B-036")
    expect(page.locator("#log")).to_contain_text("✅ Booked token B-036")


def test_check3_whatsapp_mode_books(page: Page, reset: None) -> None:
    start(page, "salma", mode="whatsapp")
    say(page, "haan", "Main aapki kya madad karun?")
    say(page, "Kal subah book karo", "Kal 10:20 baje, theek hai?")
    say(page, "haan", "WhatsApp par bheja hai")


def test_check4_machine_down_refuses_booking(page: Page, reset: None) -> None:
    dealer(page)
    page.click("#machine-down")
    expect(page.locator("#pause-badge")).to_be_visible()
    start(page, "salma")
    expect(page.locator("#log .bubble.app").first).to_contain_text("machine band hai")
    say(page, "haan", "Main aapki kya madad karun?")
    say(page, "Kal subah book karo", "booking ruki hai")
    expect(page.locator("#log")).to_contain_text("Booking refused (paused)")
    start(page, "lakshmi", mode="whatsapp")
    expect(page.locator("#log .bubble.app").first).to_contain_text("machine pani cheyyatledu")


def test_check5_failures_switch_engine_then_menu(page: Page, reset: None) -> None:
    start(page, "lakshmi")
    say(page, "Avunu", "Meeku ela sahayam cheyali?")
    say(page, "mmm hmm", "Kshaminchandi")
    expect(page.locator("#engine-badge")).to_have_text("engine: primary")
    say(page, "uh", "Kshaminchandi")
    expect(page.locator("#engine-badge")).to_have_text("engine: backup")
    say(page, "zzz", "Stock kosam 1")
    expect(page.locator("#menu")).to_be_visible()
    page.click("#menu button:has-text('2 · Queue')")
    expect(page.locator("#log .bubble.app").last).to_contain_text("18 mandi mundu unnaru")


def test_check6_late_arrival_joins_walkins(page: Page, reset: None) -> None:
    start(page, "salma")
    say(page, "haan", "madad")
    say(page, "aaj shaam book karo", "Aaj 16:00 baje, theek hai?")
    say(page, "haan", "Booking ho gayi")
    dealer(page)
    row = page.locator("#bookings-body tr", has_text="Today")
    expect(row).to_have_count(1)
    row.locator("button", has_text="+11 min (late)").click()
    expect(page.locator("#flash")).to_contain_text("was late: now walk-in")
    expect(page.locator("#queue-body")).to_contain_text("••0513")
    expect(page.locator("#k-waiting")).to_have_text("19")


def test_check7_complaint_filed_only_when_short(page: Page, reset: None) -> None:
    start(page, "lakshmi")
    say(page, "Avunu", "sahayam")
    say(page, "Naaku 15 kilolu ichharu", "15 kilolu, sare na?")
    say(page, "Avunu", "Number C-108-0003")
    say(page, "24 kilolu", "Meeku 24 kilolu raavali, 24 kilolu vachayi")
    dealer(page)
    expect(page.locator("#complaints-body")).to_contain_text("C-108-0003")
    expect(page.locator("#complaints-body tr")).to_have_count(3)


def test_check8_unknown_number_registers_and_two_cards(page: Page, reset: None) -> None:
    start(page, "unknown")
    expect(page.locator("#log .bubble.app").first).to_contain_text("okko anke cheppandi")
    say(page, "1 0 8 0 4 2 1", "Card number 1 0 8 0 4 2 1, sare na?")
    say(page, "Avunu", "card 0421 ee phone ki link chesamu")
    page.click("#hangup")
    start(page, "unknown")
    expect(page.locator("#log .bubble.app").first).to_contain_text("Card chivari ankelu 0421")
    page.click("#hangup")
    start(page, "family")
    expect(page.locator("#log .bubble.app").first).to_contain_text("2 cardlu unnayi: 0610, 0733")
    say(page, "0 7 3 3", "Meeku ela sahayam cheyali?")


def test_check11_next_judge_gets_a_fresh_lakshmi(page: Page, reset: None) -> None:
    start(page, "lakshmi")
    say(page, "Avunu", "sahayam")
    say(page, "Repu poddhuna book cheyyandi", "Repu 10:20 ki, sare na?")
    say(page, "Avunu", "Booking ayindi")
    say(page, "Hindi lo cheppandi", "Hindi mein")
    page.click("#hangup")
    start(page, "lakshmi")
    expect(page.locator("#log .bubble.app").first).to_contain_text("Card chivari ankelu 0421")
    say(page, "Avunu", "Meeku ela sahayam cheyali?")
    say(page, "Repu poddhuna book cheyyandi", "Repu 10:20 ki, sare na?")


def test_check13_no_login_wall(page: Page, reset: None) -> None:
    for path in ("/dealer", "/admin"):
        page.goto(path)
        expect(page.locator("#dash")).to_be_visible()
        expect(page.locator("#login")).to_be_hidden()
    expect(page.locator("#shops-body tr")).to_have_count(5)


def test_check14_footer_shows_build(page: Page) -> None:
    for path in ("/simulator", "/dealer", "/metrics", "/admin"):
        page.goto(path)
        expect(page.locator("footer #build")).to_contain_text("build ")
