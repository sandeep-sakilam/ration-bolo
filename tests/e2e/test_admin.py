from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e.test_accessibility import _violations


def test_admin_imports_shop_csv(page: Page, reset: None, tmp_path: Path) -> None:
    csv = tmp_path / "shops.csv"
    csv.write_text(
        "code,name,area,state_pack,sessions,families_per_hour,booked_share\n"
        "150,Fair Price Shop 150,Amberpet,telangana,08:00-12:00,30,0.5\n"
    )
    page.goto("/admin")
    expect(page.locator("#shops-body tr")).to_have_count(2)
    page.set_input_files("#shops-file", str(csv))
    page.click("#shops-form button[type=submit]")
    expect(page.locator("#flash")).to_contain_text("Imported: 1 new")
    expect(page.locator("#shops-body tr")).to_have_count(3)
    bad = tmp_path / "bad.csv"
    bad.write_text("card_no,shop_code,members,language,phone\nTS-1-0001,999,2,te,\n")
    page.set_input_files("#cards-file", str(bad))
    page.click("#cards-form button[type=submit]")
    expect(page.locator("#errors")).to_contain_text("row 2: unknown shop_code '999'")
    assert _violations(page) == []
