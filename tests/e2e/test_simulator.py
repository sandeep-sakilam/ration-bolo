from playwright.sync_api import Page, expect


def say(page: Page, text: str) -> None:
    page.fill("#textbox", text)
    page.click("#send")


def test_simulator_loads_with_key_not_set_banner(page: Page) -> None:
    page.goto("/simulator")
    expect(page.locator("h1")).to_contain_text("Ration Bolo")
    expect(page.locator(".badge.demo").first).to_have_text("Demo data")
    expect(page.locator("#status-summary")).to_contain_text("key not set")
    page.click("#status-summary")
    expect(page.locator("#status-list")).to_contain_text("key not set: WISPR_API_KEY")


def test_salma_hindi_queue_by_text(page: Page, reset: None) -> None:
    page.goto("/simulator")
    page.select_option("#caller", "salma")
    page.click("#start")
    log = page.locator("#log")
    expect(log).to_contain_text("Card ke aakhri ank 0513, theek hai?")
    say(page, "haan")
    expect(log).to_contain_text("Main aapki kya madad karun?")
    say(page, "Kitne log hain?")
    expect(log).to_contain_text("log aage hain")
    page.click("#hangup")
    expect(log).to_contain_text("Call ended")
