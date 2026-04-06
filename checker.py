import asyncio
import os
import re
import requests
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

OLX_MONITORS = [
    {
        "name": "Violoncelo",
        "url": "https://www.olx.pt/ads/q-violoncelo/?search%5Border%5D=created_at:desc",
    },
]


def send_discord(message: str) -> None:
    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"content": message},
        timeout=10,
    )
    response.raise_for_status()


async def check_olx_new_listings(name: str, url: str) -> list:
    """Returns listings posted in the last 65 minutes."""
    new_listings = []

    # Portugal: UTC+1 (summer/WEST) — DST active from late March to late October
    now_pt = datetime.now(timezone.utc) + timedelta(hours=1)
    cutoff = now_pt - timedelta(minutes=65)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        print(f"[{datetime.utcnow().isoformat()}] Loading OLX: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(4_000)

        cards = await page.query_selector_all("[data-cy='l-card']")
        print(f"OLX {name}: {len(cards)} anúncios encontrados")

        for card in cards:
            try:
                # Title
                title_el = await card.query_selector("h4, h6, [data-testid='ad-title']")
                title = (await title_el.inner_text()).strip() if title_el else "Sem título"

                # Link
                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else None
                if href and href.startswith("/"):
                    href = "https://www.olx.pt" + href

                card_text = await card.inner_text()

                match = re.search(r"[Hh]oje\s+às\s+(\d{1,2}):(\d{2})", card_text)
                if match:
                    hour, minute = int(match.group(1)), int(match.group(2))
                    listing_time = now_pt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    # Se a hora do anúncio é "no futuro", pertence ao dia anterior
                    if listing_time > now_pt:
                        listing_time -= timedelta(days=1)
                    if listing_time >= cutoff:
                        new_listings.append({"title": title, "url": href, "time": f"{hour:02d}:{minute:02d}"})

            except Exception as e:
                print(f"  Erro ao processar anúncio: {e}")

        await browser.close()

    return new_listings


async def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # OLX new listings monitor
    for monitor in OLX_MONITORS:
        try:
            new_listings = await check_olx_new_listings(monitor["name"], monitor["url"])
            if new_listings:
                for item in new_listings:
                    msg = (
                        f"🔔 **Novo anúncio OLX — {monitor['name']}**\n"
                        f"{item['title']}\n"
                        f"👉 {item['url']}\n"
                        f"⏰ Publicado hoje às {item['time']}"
                    )
                    send_discord(msg)
                    print(f"NEW LISTING: {item['title']}")
            else:
                print(f"Sem novos anúncios OLX para {monitor['name']} — checked at {now}")
        except Exception as e:
            print(f"ERROR checking OLX {monitor['name']}: {e}")
            try:
                send_discord(f"⚠️ Erro no OLX checker de {monitor['name']}:\n```{e}```")
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
