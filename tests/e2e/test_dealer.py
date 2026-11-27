from playwright.sync_api import Page, expect


def login(page: Page) -> None:
    page.goto("/dealer")
    page.fill("#pin", "1234")
    page.click("#login-form button[type=submit]")
    expect(page.locator("#dash")).to_be_visible()


def test_dealer_login_queue_and_machine_down(page: Page, reset: None) -> None:
    page.goto("/dealer")
    page.fill("#pin", "9999")
    page.click("#login-form button[type=submit]")
    expect(page.locator("#login-error")).to_have_text("Wrong PIN")
    login(page)
    expect(page.locator("#k-waiting")).to_have_text("18")
    expect(page.locator("#queue-body tr")).to_have_count(18)
    page.click("#serve")
    expect(page.locator("#k-waiting")).to_have_text("17")
    page.click("#machine-down")
    expect(page.locator("#machine-badge")).to_contain_text("back to normal in 10 min")
    expect(page.locator("#pause-badge")).to_be_visible()
    page.fill("#voice-text", "Machine working")
    page.click("#voice-form button")
    expect(page.locator("#machine-badge")).to_have_text("Machine working")
