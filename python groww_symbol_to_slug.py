import csv
import re
import time
import base64
import os
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "nse_symbols.csv"
OUTPUT_FILE = "groww_slugs_validated.csv"

GROWW_STOCKS_LIST = "https://groww.in/stocks/stocks-list"
GROWW_BASE = "https://groww.in"

REQUEST_DELAY = 0.4
TIMEOUT = 20

# Railway environment variables
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_TO = os.getenv("EMAIL_TO")

RESEND_FROM = "onboarding@resend.dev"


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
})


# ============================================================
# EXTRACT SLUG
# ============================================================

def extract_slug(url):

    match = re.search(
        r"/stocks/([^/?#]+)",
        url
    )

    if match:
        return match.group(1)

    return ""


# ============================================================
# GET GROWW STOCK DIRECTORY
# ============================================================

def get_groww_stock_links():

    print()
    print("=" * 70)
    print("LOADING GROWW STOCK DIRECTORY")
    print("=" * 70)

    try:

        response = session.get(
            GROWW_STOCKS_LIST,
            timeout=TIMEOUT
        )

        print(
            f"Groww response: "
            f"{response.status_code}"
        )

        response.raise_for_status()

    except Exception as e:

        print(
            f"ERROR loading Groww: {e}"
        )

        return []

    soup = BeautifulSoup(
        response.text,
        "lxml"
    )

    stocks = []

    for anchor in soup.find_all(
        "a",
        href=True
    ):

        href = anchor.get(
            "href",
            ""
        )

        if not href.startswith(
            "/stocks/"
        ):
            continue

        if any(
            x in href
            for x in [
                "/stocks/sectors/",
                "/stocks/filter",
                "/stocks/stocks-list"
            ]
        ):
            continue

        name = anchor.get_text(
            " ",
            strip=True
        )

        if not name:
            continue

        stocks.append({
            "name": name,
            "url": urljoin(
                GROWW_BASE,
                href
            )
        })

    # Deduplicate

    unique = {}

    for stock in stocks:

        unique[
            stock["url"]
        ] = stock

    stocks = list(
        unique.values()
    )

    print(
        f"Stock links found: "
        f"{len(stocks):,}"
    )

    return stocks


# ============================================================
# IDENTIFY NSE SYMBOL FROM GROWW PAGE
# ============================================================

def identify_stock(stock):

    try:

        response = session.get(
            stock["url"],
            timeout=TIMEOUT
        )

        if response.status_code != 200:
            return None

        html = response.text

        # ----------------------------------------------------
        # Look for NSE symbol in page source
        # ----------------------------------------------------

        patterns = [
            r'"nseSymbol"\s*:\s*"([^"]+)"',
            r'"nse_symbol"\s*:\s*"([^"]+)"',
            r'"nse"\s*:\s*"([^"]+)"',
            r'"NSE_SYMBOL"\s*:\s*"([^"]+)"',
        ]

        nse_symbol = ""

        for pattern in patterns:

            match = re.search(
                pattern,
                html,
                re.IGNORECASE
            )

            if match:

                nse_symbol = (
                    match.group(1)
                    .strip()
                    .upper()
                )

                break

        # ----------------------------------------------------
        # Fallback text search
        # ----------------------------------------------------

        if not nse_symbol:

            text = BeautifulSoup(
                html,
                "lxml"
            ).get_text(
                " ",
                strip=True
            )

            match = re.search(
                r"NSE\s*(?:symbol|code)"
                r"\s*[:\-]?\s*"
                r"([A-Z0-9&.\-]+)",
                text,
                re.IGNORECASE
            )

            if match:

                nse_symbol = (
                    match.group(1)
                    .strip()
                    .upper()
                )

        if not nse_symbol:
            return None

        return {
            "nse_symbol": nse_symbol,
            "groww_company": stock["name"],
            "groww_url": stock["url"],
            "groww_slug": extract_slug(
                stock["url"]
            )
        }

    except Exception:

        return None


# ============================================================
# VERIFY MARKET NEWS PAGE
# ============================================================

def verify_market_news(slug):

    if not slug:

        return {
            "status": "NO_SLUG",
            "url": ""
        }

    url = (
        f"{GROWW_BASE}/stocks/"
        f"{slug}/market-news"
    )

    try:

        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True
        )

        final_url = response.url

        if response.status_code != 200:

            return {
                "status":
                    f"NEWS_HTTP_{response.status_code}",
                "url":
                    final_url
            }

        final_slug = extract_slug(
            final_url
        )

        if not final_slug:

            return {
                "status":
                    "NEWS_SLUG_NOT_FOUND",
                "url":
                    final_url
            }

        return {
            "status": "VALID",
            "url": final_url
        }

    except Exception:

        return {
            "status": "NEWS_REQUEST_ERROR",
            "url": url
        }


# ============================================================
# SEND CSV BY RESEND
# ============================================================

def email_csv(
    filename,
    results
):

    print()
    print("=" * 70)
    print("EMAILING VALIDATION REPORT")
    print("=" * 70)

    if not RESEND_API_KEY:

        raise RuntimeError(
            "RESEND_API_KEY is missing "
            "from Railway Variables."
        )

    if not EMAIL_TO:

        raise RuntimeError(
            "EMAIL_TO is missing "
            "from Railway Variables."
        )

    # --------------------------------------------------------
    # Count statuses
    # --------------------------------------------------------

    counts = {}

    for result in results:

        status = result["status"]

        counts[status] = (
            counts.get(status, 0) + 1
        )

    valid = counts.get(
        "VALID",
        0
    )

    not_found = counts.get(
        "NOT_FOUND",
        0
    )

    news_failed = sum(
        count
        for status, count
        in counts.items()
        if status.startswith("NEWS_")
    )

    # --------------------------------------------------------
    # Encode attachment
    # --------------------------------------------------------

    with open(
        filename,
        "rb"
    ) as f:

        encoded = base64.b64encode(
            f.read()
        ).decode("utf-8")

    # --------------------------------------------------------
    # Email body
    # --------------------------------------------------------

    body = f"""
Groww NSE Symbol → Slug Validation Complete

Total NSE symbols:
{len(results):,}

Valid Groww mappings:
{valid:,}

Not found:
{not_found:,}

Market-news verification failures:
{news_failed:,}

The complete CSV is attached.

The CSV contains:

- NSE symbol
- Groww company name
- Groww slug
- Groww stock URL
- Groww Market News URL
- Validation status

Regards,
NSE F&O Screener
"""

    payload = {
        "from": RESEND_FROM,

        "to": [
            EMAIL_TO
        ],

        "subject":
            "Groww Slug Validation Report",

        "text":
            body,

        "attachments": [
            {
                "filename":
                    "groww_slugs_validated.csv",

                "content":
                    encoded
            }
        ]
    }

    try:

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

    except Exception as e:

        raise RuntimeError(
            f"Resend request failed: {e}"
        )

    print(
        f"Resend status: "
        f"{response.status_code}"
    )

    if response.status_code >= 400:

        print(
            response.text
        )

        raise RuntimeError(
            "Resend email failed."
        )

    print(
        "EMAIL SENT SUCCESSFULLY"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("GROWW NSE SYMBOL → SLUG VALIDATOR")
    print("=" * 70)

    # --------------------------------------------------------
    # Check input
    # --------------------------------------------------------

    if not os.path.exists(
        INPUT_FILE
    ):

        raise FileNotFoundError(
            f"{INPUT_FILE} not found."
        )

    # --------------------------------------------------------
    # Load symbols
    # --------------------------------------------------------

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        symbols = []

        for row in reader:

            symbol = (
                row.get(
                    "symbol",
                    ""
                )
                .strip()
                .upper()
            )

            if symbol:

                symbols.append(
                    symbol
                )

    print(
        f"Loaded "
        f"{len(symbols):,} NSE symbols"
    )

    target_symbols = set(
        symbols
    )

    # --------------------------------------------------------
    # Load Groww directory
    # --------------------------------------------------------

    stocks = get_groww_stock_links()

    if not stocks:

        raise RuntimeError(
            "Could not load Groww stock directory."
        )

    # --------------------------------------------------------
    # Build Groww mapping
    # --------------------------------------------------------

    print()
    print(
        "SEARCHING GROWW STOCKS..."
    )

    mapping = {}

    for index, stock in enumerate(
        stocks,
        start=1
    ):

        result = identify_stock(
            stock
        )

        if result:

            symbol = result[
                "nse_symbol"
            ]

            if symbol in target_symbols:

                mapping[
                    symbol
                ] = result

                print(
                    f"[MATCH] "
                    f"{symbol} → "
                    f"{result['groww_slug']}",
                    flush=True
                )

        if index % 100 == 0:

            print(
                f"Processed "
                f"{index:,}/"
                f"{len(stocks):,}",
                flush=True
            )

        time.sleep(
            REQUEST_DELAY
        )

    print()
    print(
        f"Groww matches found: "
        f"{len(mapping):,}"
    )

    # --------------------------------------------------------
    # Verify Market News
    # --------------------------------------------------------

    print()
    print(
        "VERIFYING MARKET NEWS LINKS..."
    )

    results = []

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        stock = mapping.get(
            symbol
        )

        # ----------------------------------------------------
        # Not found
        # ----------------------------------------------------

        if not stock:

            results.append({

                "symbol":
                    symbol,

                "groww_company":
                    "",

                "groww_slug":
                    "",

                "groww_url":
                    "",

                "market_news_url":
                    "",

                "status":
                    "NOT_FOUND"
            })

            print(
                f"[{index:,}/"
                f"{len(symbols):,}] "
                f"{symbol} → NOT_FOUND",
                flush=True
            )

            continue

        # ----------------------------------------------------
        # Verify news
        # ----------------------------------------------------

        news = verify_market_news(
            stock[
                "groww_slug"
            ]
        )

        results.append({

            "symbol":
                symbol,

            "groww_company":
                stock[
                    "groww_company"
                ],

            "groww_slug":
                stock[
                    "groww_slug"
                ],

            "groww_url":
                stock[
                    "groww_url"
                ],

            "market_news_url":
                news[
                    "url"
                ],

            "status":
                news[
                    "status"
                ]
        })

        print(
            f"[{index:,}/"
            f"{len(symbols):,}] "
            f"{symbol} → "
            f"{stock['groww_slug']} → "
            f"{news['status']}",
            flush=True
        )

        time.sleep(
            REQUEST_DELAY
        )

    # --------------------------------------------------------
    # Save CSV
    # --------------------------------------------------------

    fields = [
        "symbol",
        "groww_company",
        "groww_slug",
        "groww_url",
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

    print()
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    valid = sum(
        1
        for r in results
        if r["status"] == "VALID"
    )

    not_found = sum(
        1
        for r in results
        if r["status"] == "NOT_FOUND"
    )

    failed = len(results) - valid - not_found

    print(
        f"Total:       {len(results):,}"
    )

    print(
        f"VALID:       {valid:,}"
    )

    print(
        f"NOT FOUND:   {not_found:,}"
    )

    print(
        f"OTHER:       {failed:,}"
    )

    print()
    print(
        f"Created: {OUTPUT_FILE}"
    )

    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    email_csv(
        OUTPUT_FILE,
        results
    )

    print()
    print("=" * 70)
    print("PROCESS COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()
