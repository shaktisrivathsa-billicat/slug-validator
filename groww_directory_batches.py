import csv
import os
import time
import base64
import requests

from bs4 import BeautifulSoup
from urllib.parse import urljoin


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://groww.in"

START_URL = "https://groww.in/stocks/stocks-list"

BATCH_SIZE = 1000

OUTPUT_DIR = "groww_batches"

COMBINED_FILE = "groww_all_stocks.csv"

REQUEST_DELAY = 1.0

TIMEOUT = 30

RESEND_API_KEY = os.getenv("RESEND_API_KEY")

EMAIL_TO = os.getenv("EMAIL_TO")

FROM_EMAIL = "onboarding@resend.dev"


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36",

    "Accept-Language":
        "en-IN,en;q=0.9",

    "Accept":
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"

})


# ============================================================
# EXTRACT STOCK LINKS FROM DIRECTORY PAGE
# ============================================================

def extract_stock_links(html):

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    stocks = {}

    for anchor in soup.find_all(
        "a",
        href=True
    ):

        href = anchor.get(
            "href",
            ""
        ).strip()

        # ----------------------------------------------------
        # Only Groww stock pages
        # ----------------------------------------------------

        if not href.startswith(
            "/stocks/"
        ):
            continue

        # ----------------------------------------------------
        # Ignore directory/navigation pages
        # ----------------------------------------------------

        if href.startswith(
            "/stocks/stocks-list"
        ):
            continue

        if href.startswith(
            "/stocks?/"
        ):
            continue

        # ----------------------------------------------------
        # Remove query parameters
        # ----------------------------------------------------

        href = href.split(
            "?",
            1
        )[0]

        # ----------------------------------------------------
        # Remove trailing slash
        # ----------------------------------------------------

        href = href.rstrip("/")

        # ----------------------------------------------------
        # Must be exactly:
        #
        # /stocks/<slug>
        #
        # ----------------------------------------------------

        parts = href.split("/")

        if len(parts) != 3:
            continue

        slug = parts[2].strip()

        if not slug:
            continue

        # ----------------------------------------------------
        # Ignore obvious non-stock pages
        # ----------------------------------------------------

        ignored = {

            "stocks",
            "stocks-list",
            "screens",
            "sectors",
            "futures",
            "options",
            "market-news"

        }

        if slug.lower() in ignored:
            continue

        # ----------------------------------------------------
        # Build URL
        # ----------------------------------------------------

        stock_url = urljoin(
            BASE_URL,
            href
        )

        # ----------------------------------------------------
        # Company name
        # ----------------------------------------------------

        company = anchor.get_text(
            " ",
            strip=True
        )

        # ----------------------------------------------------
        # Store
        # ----------------------------------------------------

        stocks[stock_url] = {

            "groww_company":
                company,

            "groww_slug":
                slug,

            "groww_stock_url":
                stock_url,

            "market_news_url":
                f"{stock_url}/market-news"

        }

    return list(
        stocks.values()
    )


# ============================================================
# EXTRACT PAGINATION LINKS
# ============================================================

def extract_pagination_links(
    html,
    current_url
):

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    pages = set()

    for anchor in soup.find_all(
        "a",
        href=True
    ):

        href = anchor.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        if not href.startswith(
            "/stocks/stocks-list"
        ):
            continue

        href = href.split(
            "?",
            1
        )[0]

        href = href.rstrip("/")

        url = urljoin(
            BASE_URL,
            href
        )

        pages.add(url)

    return pages


# ============================================================
# SCRAPE GROWw DIRECTORY
# ============================================================

def crawl_groww_directory():

    print()
    print("=" * 75)
    print("GROWW DIRECTORY CRAWLER")
    print("=" * 75)

    visited_pages = set()

    pending_pages = [
        START_URL
    ]

    all_stocks = {}

    page_number = 0

    while pending_pages:

        url = pending_pages.pop(0)

        if url in visited_pages:
            continue

        visited_pages.add(url)

        page_number += 1

        print()
        print(
            "-" * 75
        )

        print(
            f"Directory page #{page_number}"
        )

        print(
            f"URL: {url}"
        )

        try:

            response = session.get(
                url,
                timeout=TIMEOUT
            )

            print(
                f"HTTP status: "
                f"{response.status_code}"
            )

            if response.status_code != 200:

                print(
                    "Page failed - skipping."
                )

                continue

            html = response.text

        except Exception as e:

            print(
                f"REQUEST ERROR: {e}"
            )

            continue

        # ----------------------------------------------------
        # Extract stocks
        # ----------------------------------------------------

        stocks = extract_stock_links(
            html
        )

        print(
            f"Stock links on page: "
            f"{len(stocks)}"
        )

        new_stocks = 0

        for stock in stocks:

            stock_url = (
                stock[
                    "groww_stock_url"
                ]
            )

            if stock_url not in all_stocks:

                all_stocks[
                    stock_url
                ] = stock

                new_stocks += 1

        print(
            f"New stocks discovered: "
            f"{new_stocks}"
        )

        print(
            f"TOTAL UNIQUE STOCKS: "
            f"{len(all_stocks)}"
        )

        # ----------------------------------------------------
        # Discover additional pages
        # ----------------------------------------------------

        pagination = (
            extract_pagination_links(
                html,
                url
            )
        )

        new_pages = 0

        for page_url in sorted(
            pagination
        ):

            if page_url not in visited_pages:

                if page_url not in pending_pages:

                    pending_pages.append(
                        page_url
                    )

                    new_pages += 1

        print(
            f"New directory pages found: "
            f"{new_pages}"
        )

        # ----------------------------------------------------
        # Delay
        # ----------------------------------------------------

        time.sleep(
            REQUEST_DELAY
        )

    print()
    print("=" * 75)
    print("DIRECTORY CRAWL COMPLETE")
    print("=" * 75)

    print(
        f"Directory pages visited: "
        f"{len(visited_pages)}"
    )

    print(
        f"Unique Groww stocks: "
        f"{len(all_stocks)}"
    )

    return list(
        all_stocks.values()
    )


# ============================================================
# SORT STOCKS
# ============================================================

def sort_stocks(
    stocks
):

    return sorted(
        stocks,
        key=lambda x: (
            x[
                "groww_company"
            ] or ""
        ).lower()
    )


# ============================================================
# SAVE CSV
# ============================================================

def save_csv(
    stocks,
    filename
):

    fields = [

        "groww_company",

        "groww_slug",

        "groww_stock_url",

        "market_news_url"

    ]

    with open(

        filename,

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
            stocks
        )


# ============================================================
# CREATE BATCH FILES
# ============================================================

def create_batches(
    stocks
):

    print()
    print("=" * 75)
    print("CREATING CSV BATCHES")
    print("=" * 75)

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    total = len(
        stocks
    )

    batch_number = 1

    created_files = []

    for start in range(
        0,
        total,
        BATCH_SIZE
    ):

        end = min(
            start + BATCH_SIZE,
            total
        )

        batch = stocks[
            start:end
        ]

        filename = os.path.join(

            OUTPUT_DIR,

            f"groww_batch_{batch_number:03d}.csv"

        )

        save_csv(
            batch,
            filename
        )

        created_files.append(
            filename
        )

        print(
            f"Batch "
            f"{batch_number:03d}: "
            f"{len(batch):,} stocks "
            f"→ {filename}"
        )

        batch_number += 1

    # --------------------------------------------------------
    # Combined CSV
    # --------------------------------------------------------

    save_csv(
        stocks,
        COMBINED_FILE
    )

    print()
    print(
        f"Combined file: "
        f"{COMBINED_FILE}"
    )

    print(
        f"Total rows: "
        f"{total:,}"
    )

    return created_files


# ============================================================
# CREATE EMAIL BODY
# ============================================================

def get_summary(
    stocks,
    batch_files
):

    total = len(
        stocks
    )

    return f"""
Groww Directory Crawl Complete

Total unique Groww stock pages:
{total:,}

CSV batches created:
{len(batch_files)}

Batch size:
1,000 stocks

Combined CSV:
{COMBINED_FILE}

Each row contains:

- Groww company name
- Groww slug
- Groww stock URL
- Groww Market News URL

The URLs were extracted from the Groww
stock directory rather than generated
from company names.

Regards,
NSE F&O Screener
"""


# ============================================================
# EMAIL FILE
# ============================================================

def send_resend_email(
    filename,
    subject,
    body
):

    if not RESEND_API_KEY:

        print(
            "RESEND_API_KEY not configured."
        )

        return False

    if not EMAIL_TO:

        print(
            "EMAIL_TO not configured."
        )

        return False

    try:

        with open(
            filename,
            "rb"
        ) as f:

            encoded = (
                base64.b64encode(
                    f.read()
                ).decode(
                    "utf-8"
                )
            )

        payload = {

            "from":
                FROM_EMAIL,

            "to":
                [EMAIL_TO],

            "subject":
                subject,

            "text":
                body,

            "attachments": [

                {

                    "filename":
                        os.path.basename(
                            filename
                        ),

                    "content":
                        encoded

                }

            ]

        }

        response = requests.post(

            "https://api.resend.com/emails",

            headers={

                "Authorization":
                    f"Bearer "
                    f"{RESEND_API_KEY}",

                "Content-Type":
                    "application/json"

            },

            json=payload,

            timeout=120

        )

        print(
            f"Resend status: "
            f"{response.status_code}"
        )

        if response.status_code >= 400:

            print(
                response.text
            )

            return False

        print(
            "EMAIL SENT SUCCESSFULLY"
        )

        return True

    except Exception as e:

        print(
            f"EMAIL ERROR: {e}"
        )

        return False


# ============================================================
# EMAIL BATCHES
# ============================================================

def email_batches(
    batch_files,
    stocks
):

    print()
    print("=" * 75)
    print("EMAILING RESULTS")
    print("=" * 75)

    # --------------------------------------------------------
    # First email: combined CSV
    # --------------------------------------------------------

    body = get_summary(
        stocks,
        batch_files
    )

    send_resend_email(

        COMBINED_FILE,

        "Groww Complete Directory - Combined CSV",

        body

    )

    # --------------------------------------------------------
    # Email individual batches
    # --------------------------------------------------------

    for filename in batch_files:

        batch_name = os.path.basename(
            filename
        )

        body = f"""
Groww Directory Batch

File:
{batch_name}

This file contains up to 1,000
Groww stock directory entries.

Columns:

- Groww company
- Groww slug
- Groww stock URL
- Groww Market News URL

Regards,
NSE F&O Screener
"""

        send_resend_email(

            filename,

            f"Groww Directory - {batch_name}",

            body

        )

        # Avoid sending too rapidly
        time.sleep(2)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 75)
    print("GROWW COMPLETE DIRECTORY → CSV BATCHES")
    print("=" * 75)

    # --------------------------------------------------------
    # Crawl
    # --------------------------------------------------------

    stocks = (
        crawl_groww_directory()
    )

    if not stocks:

        raise RuntimeError(
            "No Groww stocks found."
        )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    stocks = sort_stocks(
        stocks
    )

    # --------------------------------------------------------
    # Create batches
    # --------------------------------------------------------

    batch_files = (
        create_batches(
            stocks
        )
    )

    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    email_batches(
        batch_files,
        stocks
    )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print()
    print("=" * 75)
    print("ALL DONE")
    print("=" * 75)

    print(
        f"Total Groww stocks: "
        f"{len(stocks):,}"
    )

    print(
        f"Batch files: "
        f"{len(batch_files)}"
    )

    print(
        f"Combined file: "
        f"{COMBINED_FILE}"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
