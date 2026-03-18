import asyncio
import os
import json
import requests
from datetime import datetime
from playwright.async_api import async_playwright

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

PRODUCTS = [
    {
        "name": "Samsung Galaxy Buds4 Pro (Preto)",
        "url": "https://www.vodafone.pt/loja/acessorios/som/samsung-galaxy-buds4-pro.html?segment=consumer&color=preto&paymentType=pvp",
    },
    {
        "name": "Samsung Galaxy Buds4 Pro (Branco)",
        "url": "https://www.vodafone.pt/loja/acessorios/som/samsung-galaxy-buds4-pro.html?segment=consumer&color=branco&paymentType=pvp",
    },
]


def send_discord(message: str) -> None:
    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"content": message},
        timeout=10,
    )
    response.raise_for_status()


async def check_availability(url: str) -> bool:
    api_stock: dict = {}

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

        async def handle_response(response):
            try:
                r_url = response.url.lower()
                if any(k in r_url for k in ["product", "stock", "catalog", "pdp", "item"]):
                    if response.status == 200:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            data = await response.json()
                            text = json.dumps(data).lower()
                            if "stock" in text or "availability" in text:
                                api_stock.update({"raw": data, "url": response.url})
            except Exception:
                pass

        page.on("response", handle_response)

        print(f"[{datetime.utcnow().isoformat()}] Loading: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(6_000)  # Extra time for Vue to render

        if api_stock:
            raw = json.dumps(api_stock.get("raw", {})).lower()
            print(f"API data captured from: {api_stock.get('url')}")
            if "instock" in raw or '"stock":true' in raw or '"available":true' in raw:
                await browser.close()
                return True
            if "outofstock" in raw or '"stock":false' in raw or '"available":false' in raw:
                await browser.close()
                return False

        btn = await page.query_selector("#add-to-cart-toast")
        if btn:
            classes = await btn.get_attribute("class") or ""
            is_disabled = "button--disabled" in classes or "disabled" in classes
            btn_text = (await btn.inner_text()).strip().lower()
            print(f"Button found | classes: {classes!r} | text: {btn_text!r}")
            if not is_disabled and btn_text and "indispon" not in btn_text and "esgot" not in btn_text:
                await browser.close()
                return True
        else:
            print("Button #add-to-cart-toast NOT found")

        body_text = (await page.inner_text("body")).lower()

        unavailable_keywords = ["esgotado", "indisponível", "sem stock", "stockunavailable"]
        available_keywords = ["adicionar ao carrinho", "adicionar", "stockavailable"]

        for kw in available_keywords:
            if kw in body_text:
                await browser.close()
                return True

        for kw in unavailable_keywords:
            if kw in body_text:
                await browser.close()
                return False

        await browser.close()

    print("Could not determine availability — assuming unavailable.")
    return False


async def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    for product in PRODUCTS:
        try:
            available = await check_availability(product["url"])

            if available:
                msg = (
                    f"🎉 **DISPONÍVEL!**\n"
                    f"{product['name']} está disponível na Vodafone!\n"
                    f"👉 {product['url']}\n"
                    f"⏰ {now}"
                )
                send_discord(msg)
                print(f"AVAILABLE — {product['name']} — Discord notification sent.")
            else:
                print(f"NOT available: {product['name']} — checked at {now}")

        except Exception as e:
            print(f"ERROR checking {product['name']}: {e}")
            try:
                send_discord(f"⚠️ Erro no checker de {product['name']}:\n```{e}```")
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
