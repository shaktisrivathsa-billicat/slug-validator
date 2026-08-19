import csv
import re
import time
import base64
import os
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "nse_symbols.csv"
OUTPUT_FILE = "groww_slugs_validated.csv"

GROWW_BASE = "https://groww.in"

# Groww website search
SEARCH_URL = "https://groww.in/search"

REQUEST_DELAY = 0.7
TIMEOUT = 20

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_TO = os.getenv("EMAIL_TO")

RESEND_FROM = "onboarding@resend.dev"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
})


# ============================================================
# EXTRACT STOCK SLUG
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
# EXTRACT NSE SYMBOL FROM PAGE
# ============================================================

def extract_nse_symbol(html):

    patterns = [

        r'"nseSymbol"\s*:\s*"([^"]+)"',

        r'"nse_symbol"\s*:\s*"([^"]+)"',

        r'"nse"\s*:\s*"([^"]+)"',

        r'"NSE_SYMBOL"\s*:\s*"([^"]+)"',

        r'"tradingSymbol"\s*:\s*"([^"]+)"',

        r'"trading_symbol"\s*:\s*"([^"]+)"',

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE
        )

        if match:

            return (
                match.group(1)
                .strip()
                .upper()
            )

    # --------------------------------------------------------
    # Fallback: visible text
    # --------------------------------------------------------

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    text = soup.get_text(
        " ",
        strip=True
    )

    patterns = [

        r"NSE\s+symbol\s*[:\-]?\s*"
        r"([A-Z0-9&.\-]+)",

        r"NSE\s*[:\-]\s*"
        r"([A-Z0-9&.\-]+)",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return (
                match.group(1)
                .strip()
                .upper()
            )

    return ""


# ============================================================
# EXTRACT COMPANY NAME
# ============================================================

def extract_company_name(html):

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    # Try title first
    if soup.title:

        title = soup.title.get_text(
            " ",
            strip=True
        )

        if title:

            # Remove common Groww suffixes
            title = re.sub(
                r"\s*[-|]\s*Groww.*$",
                "",
                title,
                flags=re.IGNORECASE
            )

            return title.strip()

    # Try H1
    h1 = soup.find("h1")

    if h1:

        return h1.get_text(
            " ",
            strip=True
        )

    return ""


# ============================================================
# FIND STOCK LINKS IN SEARCH RESPONSE
# ============================================================

def extract_stock_links(html):

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    links = []

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

        # Exclude generic pages
        if href in [
            "/stocks",
            "/stocks/",
            "/stocks/stocks-list",
            "/stocks/stocks-list/",
        ]:
            continue

        text = anchor.get_text(
            " ",
            strip=True
        )

        url = urljoin(
            GROWW_BASE,
            href
        )

        links.append({
            "url": url,
            "text": text
        })

    # Deduplicate
    unique = {}

    for item in links:

        unique[
            item["url"]
        ] = item

    return list(
        unique.values()
    )


# ============================================================
# SEARCH GROWW FOR ONE SYMBOL
# ============================================================

def search_groww(
    symbol
):

    print(
        f"Searching Groww for {symbol}...",
        flush=True
    )

    # --------------------------------------------------------
    # Attempt website search
    # --------------------------------------------------------

    search_urls = [

        (
            f"{SEARCH_URL}"
            f"?q={quote(symbol)}"
        ),

        (
            f"{GROWW_BASE}/search/"
            f"{quote(symbol)}"
        ),

    ]

    candidates = []

    for search_url in search_urls:

        try:

            response = session.get(
                search_url,
                timeout=TIMEOUT,
                allow_redirects=True
            )

            if response.status_code != 200:
                continue

            links = extract_stock_links(
                response.text
            )

            candidates.extend(
                links
            )

            if candidates:
                break

        except Exception:

            continue

    # Deduplicate candidates

    unique = {}

    for candidate in candidates:

        unique[
            candidate["url"]
        ] = candidate

    candidates = list(
        unique.values()
    )

    if not candidates:

        return None

    print(
        f"  Search candidates: "
        f"{len(candidates)}",
        flush=True
    )

    # --------------------------------------------------------
    # Check each candidate
    # --------------------------------------------------------

    for candidate in candidates:

        url = candidate["url"]

        try:

            response = session.get(
                url,
                timeout=TIMEOUT
            )

            if response.status_code != 200:
                continue

            html = response.text

            page_symbol = (
                extract_nse_symbol(
                    html
                )
            )

            if page_symbol != symbol:
                continue

            company_name = (
                extract_company_name(
                    html
                )
            )

            slug = extract_slug(
                response.url
            )

            if not slug:
                continue

            return {
                "symbol": symbol,
                "groww_company":
                    company_name,
                "groww_slug":
                    slug,
                "groww_url":
                    response.url,
            }

        except Exception:

            continue

    return None


# ============================================================
# VERIFY MARKET NEWS
# ============================================================

def verify_market_news(
    slug,
    symbol
):

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

        if response.status_code != 200:

            return {
                "status":
                    f"NEWS_HTTP_{response.status_code}",
                "url":
                    response.url
            }

        # Verify the redirected page still
        # corresponds to the requested stock.
        page_symbol = extract_nse_symbol(
            response.text
        )

        if (
            page_symbol
            and page_symbol != symbol
        ):

            return {
                "status":
                    "NEWS_SYMBOL_MISMATCH",
                "url":
                    response.url
            }

        final_slug = extract_slug(
            response.url
        )

        if not final_slug:

            return {
                "status":
                    "NEWS_SLUG_NOT_FOUND",
                "url":
                    response.url
            }

        return {
            "status":
                "VALID",
            "url":
                response.url
        }

    except Exception:

        return {
            "status":
                "NEWS_REQUEST_ERROR",
            "url":
                url
        }


# ============================================================
# EMAIL CSV
# ============================================================

def send_email(
    filename,
    results
):

    print()
    print("=" * 70)
    print("SENDING VALIDATION REPORT")
    print("=" * 70)

    if not RESEND_API_KEY:

        raise RuntimeError(
            "RESEND_API_KEY is not configured."
        )

    if not EMAIL_TO:

        raise RuntimeError(
            "EMAIL_TO is not configured."
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Encode CSV
    # --------------------------------------------------------

    with open(
        filename,
        "rb"
    ) as f:

        encoded = base64.b64encode(
            f.read()
        ).decode(
            "utf-8"
        )

    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    body = f"""
Groww NSE Symbol → Slug Validation Complete

Total NSE symbols:
{len(results):,}

VALID:
{valid:,}

NOT FOUND:
{not_found:,}

OTHER:
{other:,}

The attached CSV contains:

- NSE symbol
- Groww company name
- Actual Groww slug
- Groww stock URL
- Groww Market News URL
- Validation status

The script searched Groww for each NSE symbol and
then verified the corresponding Market News page.

Regards,
NSE F&O Screener
"""

    payload = {

        "from":
            RESEND_FROM,

        "to":
            [EMAIL_TO],

        "subject":
            "Groww Slug Validation - Completed",

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
    # Read your actual CSV
    # Column is "symbols"
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
                    "symbols",
                    ""
                )
                .strip()
                .upper()
            )

            if symbol:

                symbols.append(
                    symbol
                )

    # Remove duplicates
    symbols = list(
        dict.fromkeys(
            symbols
        )
    )

    print(
        f"Loaded {len(symbols):,} NSE symbols"
    )

    # --------------------------------------------------------
    # Search every NSE symbol
    # --------------------------------------------------------

    results = []

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        print()
        print(
            f"[{index}/{len(symbols)}]"
        )

        stock = search_groww(
            symbol
        )

        # ----------------------------------------------------
        # Not found
        # ----------------------------------------------------

        if not stock:

            print(
                f"  NOT FOUND: {symbol}",
                flush=True
            )

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

            time.sleep(
                REQUEST_DELAY
            )

            continue

        print(
            f"  MATCH: "
            f"{stock['groww_company']}",
            flush=True
        )

        print(
            f"  SLUG: "
            f"{stock['groww_slug']}",
            flush=True
        )

        # ----------------------------------------------------
        # Verify Market News
        # ----------------------------------------------------

        news = verify_market_news(
            stock["groww_slug"],
            symbol
        )

        print(
            f"  MARKET NEWS: "
            f"{news['status']}",
            flush=True
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

        time.sleep(
            REQUEST_DELAY
        )

    # --------------------------------------------------------
    # Write output
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

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

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
    print("VALIDATION COMPLETE")
    print("=" * 70)

    print(
        f"Total:     {len(results):,}"
    )

    print(
        f"VALID:     {valid:,}"
    )

    print(
        f"NOT FOUND: {not_found:,}"
    )

    print(
        f"OTHER:     {other:,}"
    )

    print()
    print(
        f"Created: {OUTPUT_FILE}"
    )

    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    send_email(
        OUTPUT_FILE,
        results
    )

    print()
    print("=" * 70)
    print("ALL DONE")
    print("=" * 70)


if __name__ == "__main__":

    main()
