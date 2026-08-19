import asyncio
import csv
import os
import base64
import requests

from playwright.async_api import async_playwright


INPUT_FILE = "nse_symbols.csv"
OUTPUT_FILE = "groww_slugs_validated.csv"

GROWW_URL = "https://groww.in/stocks"

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_TO = os.getenv("EMAIL_TO")

RESEND_FROM = "onboarding@resend.dev"


# ============================================================
# READ SYMBOLS
# ============================================================

def load_symbols():

    symbols = []

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            symbol = (
                row.get("symbols", "")
                .strip()
                .upper()
            )

            if symbol:
                symbols.append(symbol)

    # Remove duplicates while preserving order
    return list(dict.fromkeys(symbols))


# ============================================================
# EXTRACT SLUG
# ============================================================

def extract_slug(url):

    if "/stocks/" not in url:
        return ""

    part = url.split("/stocks/", 1)[1]

    return part.split("/", 1)[0].split("?", 1)[0]


# ============================================================
# SEARCH ONE SYMBOL
# ============================================================

async def search_symbol(
    page,
    symbol
):

    print(
        f"Searching Groww for {symbol}...",
        flush=True
    )

    try:

        # ----------------------------------------------------
        # Open Groww stocks page
        # ----------------------------------------------------

        await page.goto(
            GROWW_URL,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(2000)

        # ----------------------------------------------------
        # Find search input
        # ----------------------------------------------------

        search = page.locator(
            'input[placeholder*="Search" i]'
        ).first

        if await search.count() == 0:

            search = page.locator(
                'input[type="search"]'
            ).first

        if await search.count() == 0:

            search = page.locator(
                'input'
            ).first

        if await search.count() == 0:

            return {
                "status": "SEARCH_BOX_NOT_FOUND",
                "stock_url": "",
                "market_news_url": "",
                "slug": "",
                "company": ""
            }

        # ----------------------------------------------------
        # Enter symbol
        # ----------------------------------------------------

        await search.click()

        await search.fill("")

        await search.fill(symbol)

        # Wait for Groww's search results
        await page.wait_for_timeout(2000)

        # ----------------------------------------------------
        # Find stock links currently displayed
        # ----------------------------------------------------

        links = page.locator(
            'a[href*="/stocks/"]'
        )

        count = await links.count()

        print(
            f"  Search results links: {count}",
            flush=True
        )

        candidates = []

        for i in range(count):

            link = links.nth(i)

            try:

                href = await link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                if not href.startswith(
                    "/stocks/"
                ):

                    continue

                text = await link.inner_text()

                candidates.append({
                    "href": href,
                    "text": text
                })

            except Exception:
                continue

        # ----------------------------------------------------
        # Look for exact NSE symbol/company match
        # ----------------------------------------------------

        selected = None

        symbol_upper = symbol.upper()

        for candidate in candidates:

            text = (
                candidate["text"]
                .strip()
                .upper()
            )

            href = candidate["href"]

            # Exact symbol appearing in result
            if symbol_upper in text:

                selected = candidate
                break

        # ----------------------------------------------------
        # If exact symbol isn't visible,
        # inspect candidate pages
        # ----------------------------------------------------

        if selected is None:

            print(
                "  Exact symbol not visible; "
                "checking candidate pages...",
                flush=True
            )

            for candidate in candidates:

                url = (
                    "https://groww.in"
                    + candidate["href"]
                )

                try:

                    check_page = await page.context.new_page()

                    await check_page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=20000
                    )

                    await check_page.wait_for_timeout(
                        1000
                    )

                    body = (
                        await check_page.locator(
                            "body"
                        ).inner_text()
                    )

                    body_upper = body.upper()

                    if (
                        f"NSE SYMBOL {symbol_upper}"
                        in body_upper
                        or
                        f"NSE: {symbol_upper}"
                        in body_upper
                        or
                        f"NSE {symbol_upper}"
                        in body_upper
                    ):

                        selected = candidate

                        await check_page.close()

                        break

                    await check_page.close()

                except Exception:
                    continue

        # ----------------------------------------------------
        # Nothing found
        # ----------------------------------------------------

        if selected is None:

            return {
                "status": "NOT_FOUND",
                "stock_url": "",
                "market_news_url": "",
                "slug": "",
                "company": ""
            }

        # ----------------------------------------------------
        # Build stock URL
        # ----------------------------------------------------

        href = selected["href"]

        stock_url = (
            "https://groww.in"
            + href
        )

        slug = extract_slug(
            stock_url
        )

        company = (
            selected["text"]
            .strip()
        )

        print(
            f"  MATCH: {company}",
            flush=True
        )

        print(
            f"  URL: {stock_url}",
            flush=True
        )

        # ----------------------------------------------------
        # Verify Market News page
        # ----------------------------------------------------

        news_url = (
            f"https://groww.in/stocks/"
            f"{slug}/market-news"
        )

        news_page = await page.context.new_page()

        try:

            response = await news_page.goto(
                news_url,
                wait_until="domcontentloaded",
                timeout=20000
            )

            if response:

                status_code = response.status

            else:

                status_code = 0

            final_url = news_page.url

        finally:

            await news_page.close()

        if status_code == 200:

            news_status = "VALID"

        else:

            news_status = (
                f"NEWS_HTTP_{status_code}"
            )

        print(
            f"  MARKET NEWS: "
            f"{news_status}",
            flush=True
        )

        return {
            "status": news_status,
            "stock_url": stock_url,
            "market_news_url": final_url,
            "slug": extract_slug(final_url),
            "company": company
        }

    except Exception as e:

        print(
            f"  ERROR: {e}",
            flush=True
        )

        return {
            "status": "ERROR",
            "stock_url": "",
            "market_news_url": "",
            "slug": "",
            "company": ""
        }


# ============================================================
# EMAIL CSV
# ============================================================

def send_email():

    print()
    print(
        "Sending CSV by email..."
    )

    if not RESEND_API_KEY:

        raise RuntimeError(
            "RESEND_API_KEY is missing."
        )

    if not EMAIL_TO:

        raise RuntimeError(
            "EMAIL_TO is missing."
        )

    with open(
        OUTPUT_FILE,
        "rb"
    ) as f:

        encoded = base64.b64encode(
            f.read()
        ).decode("utf-8")

    # Count results

    with open(
        OUTPUT_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    valid = sum(
        1
        for row in rows
        if row["status"] == "VALID"
    )

    not_found = sum(
        1
        for row in rows
        if row["status"] == "NOT_FOUND"
    )

    other = (
        len(rows)
        - valid
        - not_found
    )

    body = f"""
Groww Stock URL Validation Complete

Total symbols: {len(rows)}

Valid Market News links: {valid}

Not found: {not_found}

Other/errors: {other}

The attached CSV contains:

NSE symbol
Groww company name
Groww slug
Groww stock URL
Groww Market News URL
Status

The script searched the Groww Stocks page
for each NSE symbol using browser automation.

Regards,
NSE F&O Screener
"""

    payload = {

        "from": RESEND_FROM,

        "to": [
            EMAIL_TO
        ],

        "subject":
            "Groww Stock URL Validation Complete",

        "text":
            body,

        "attachments": [

            {
                "filename":
                    OUTPUT_FILE,

                "content":
                    encoded
            }
        ]
    }

    response = requests.post(

        "https://api.resend.com/emails",

        headers={
            "Authorization":
                f"Bearer {RESEND_API_KEY}",

            "Content-Type":
                "application/json"
        },

        json=payload,

        timeout=60
    )

    print(
        "Resend status:",
        response.status_code
    )

    if response.status_code >= 400:

        print(
            response.text
        )

        raise RuntimeError(
            "Email failed."
        )

    print(
        "EMAIL SENT SUCCESSFULLY"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print("=" * 70)
    print("GROWW SEARCH-BAR STOCK URL FINDER")
    print("=" * 70)

    symbols = load_symbols()

    print(
        f"Loaded {len(symbols)} NSE symbols"
    )

    results = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )

        context = await browser.new_context(
            viewport={
                "width": 1440,
                "height": 900
            }
        )

        page = await context.new_page()

        for index, symbol in enumerate(
            symbols,
            start=1
        ):

            print()
            print(
                f"[{index}/{len(symbols)}]"
            )

            result = await search_symbol(
                page,
                symbol
            )

            results.append({

                "symbol":
                    symbol,

                "groww_company":
                    result["company"],

                "groww_slug":
                    result["slug"],

                "groww_stock_url":
                    result["stock_url"],

                "market_news_url":
                    result["market_news_url"],

                "status":
                    result["status"]
            })

            # Small delay between searches
            await page.wait_for_timeout(
                1000
            )

        await browser.close()

    # ========================================================
    # SAVE CSV
    # ========================================================

    fields = [
        "symbol",
        "groww_company",
        "groww_slug",
        "groww_stock_url",
        "market_news_url",
        "status"
    ]

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()

        writer.writerows(
            results
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    valid = sum(
        1
        for row in results
        if row["status"] == "VALID"
    )

    not_found = sum(
        1
        for row in results
        if row["status"] == "NOT_FOUND"
    )

    other = (
        len(results)
        - valid
        - not_found
    )

    print()
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)

    print(
        f"Total:     {len(results)}"
    )

    print(
        f"VALID:     {valid}"
    )

    print(
        f"NOT FOUND: {not_found}"
    )

    print(
        f"OTHER:     {other}"
    )

    print(
        f"Created:   {OUTPUT_FILE}"
    )

    # ========================================================
    # EMAIL
    # ========================================================

    send_email()


if __name__ == "__main__":

    asyncio.run(main())
