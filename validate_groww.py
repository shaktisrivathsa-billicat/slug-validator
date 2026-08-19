import csv
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


INPUT_FILE = "groww_slugs.csv"
OUTPUT_FILE = "groww_slugs_validated.csv"

REQUEST_DELAY = 0.25
TIMEOUT = 20

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
})


def extract_final_slug(url):

    match = re.search(
        r"/stocks/([^/?#]+)",
        url
    )

    if match:
        return match.group(1)

    return ""


def validate_slug(symbol, company_name, slug):

    if not slug:
        return {
            "symbol": symbol,
            "company_name": company_name,
            "original_slug": "",
            "validated_slug": "",
            "status": "MISSING",
            "final_url": "",
            "http_status": "",
        }

    url = (
        "https://groww.in/stocks/"
        f"{slug}/market-news"
    )

    try:

        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True
        )

        final_url = response.url

        final_slug = extract_final_slug(
            final_url
        )

        if response.status_code != 200:

            return {
                "symbol": symbol,
                "company_name": company_name,
                "original_slug": slug,
                "validated_slug": final_slug,
                "status": f"HTTP_{response.status_code}",
                "final_url": final_url,
                "http_status": response.status_code,
            }

        soup = BeautifulSoup(
            response.text,
            "lxml"
        )

        page_text = soup.get_text(
            " ",
            strip=True
        ).lower()

        company_words = re.findall(
            r"[a-z0-9]+",
            company_name.lower()
        )

        company_words = [
            word
            for word in company_words
            if len(word) >= 4
        ]

        matches = 0

        for word in company_words:

            if word in page_text:
                matches += 1

        # ----------------------------------------------------
        # Determine validation status
        # ----------------------------------------------------

        if (
            final_slug
            and final_slug != slug
            and matches >= 1
        ):

            status = "CORRECTED"

        elif matches >= 1:

            status = "VALID"

        elif final_slug:

            status = "PAGE_FOUND_NAME_UNCONFIRMED"

        else:

            status = "INVALID"

        return {
            "symbol": symbol,
            "company_name": company_name,
            "original_slug": slug,
            "validated_slug": final_slug,
            "status": status,
            "final_url": final_url,
            "http_status": response.status_code,
        }

    except requests.RequestException as e:

        return {
            "symbol": symbol,
            "company_name": company_name,
            "original_slug": slug,
            "validated_slug": "",
            "status": "REQUEST_ERROR",
            "final_url": url,
            "http_status": "",
        }

    except Exception as e:

        return {
            "symbol": symbol,
            "company_name": company_name,
            "original_slug": slug,
            "validated_slug": "",
            "status": "ERROR",
            "final_url": url,
            "http_status": "",
        }


def main():

    print("=" * 70)
    print("GROWW SLUG VALIDATOR")
    print("=" * 70)

    input_path = Path(
        INPUT_FILE
    )

    if not input_path.exists():

        raise FileNotFoundError(
            f"{INPUT_FILE} not found."
        )

    with open(
        input_path,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        rows = list(reader)

    print(
        f"Loaded {len(rows):,} Groww mappings"
    )

    results = []

    for index, row in enumerate(
        rows,
        start=1
    ):

        symbol = (
            row.get("symbol", "")
            .strip()
            .upper()
        )

        company_name = (
            row.get("company_name", "")
            .strip()
        )

        slug = (
            row.get("groww_slug", "")
            .strip()
        )

        print(
            f"[{index:,}/{len(rows):,}] "
            f"{symbol} → {slug}"
        )

        result = validate_slug(
            symbol,
            company_name,
            slug
        )

        results.append(result)

        print(
            f"    {result['status']}"
        )

        if result["validated_slug"]:

            print(
                f"    Final slug: "
                f"{result['validated_slug']}"
            )

        time.sleep(
            REQUEST_DELAY
        )

    # --------------------------------------------------------
    # Write validation report
    # --------------------------------------------------------

    fieldnames = [
        "symbol",
        "company_name",
        "original_slug",
        "validated_slug",
        "status",
        "final_url",
        "http_status",
    ]

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        writer.writeheader()

        writer.writerows(
            results
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    counts = {}

    for result in results:

        status = result["status"]

        counts[status] = (
            counts.get(status, 0)
            + 1
        )

    print()
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)

    for status, count in sorted(
        counts.items()
    ):

        print(
            f"{status:<35} {count:,}"
        )

    print()
    print(
        f"Output: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
