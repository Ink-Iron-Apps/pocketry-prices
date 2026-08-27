#!/usr/bin/env python3
"""Nightly price pull: source -> normalised -> archive -> publish.

Usage:
    python tools/pull_prices.py --out app/assets --archive archive/

Runs dev-side, once a day. The app never calls a price API: it fetches ONE
static file from our own bucket, which is what keeps marginal cost per user at
zero and makes a one-time purchase viable at any scale.

Output:
    prices-YYYY-MM-DD.csv   productId,finishIndex,market,low,high
    manifest.json           latest date, per-source timestamps, checksum
"""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sys
import urllib.request

BASE = 'https://tcgcsv.com/tcgplayer'
POKEMON_CATEGORY = 3

# Must match the Finish enum in app/lib/core/models/finish.dart.
FINISH_INDEX = {
    'Normal': 1,
    'Holofoil': 2,
    'Reverse Holofoil': 3,
    '1st Edition': 4,
    '1st Edition Holofoil': 5,
    'Unlimited': 6,
    'Unlimited Holofoil': 7,
}

# A pull that loses a large share of its rows is far worse than a stale file:
# stale is visible to the user, wrong is silent. Refuse to publish either.
MIN_ROWS = 30_000
MAX_NULL_SHARE = 0.10


# The source rejects Python's default User-Agent with a 401, so identify
# properly rather than anonymously.
USER_AGENT = ('Mozilla/5.0 (compatible; Pocketry/0.1; '
              '+https://inknironapps.com)')


def fetch_json(url, attempts=4):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except Exception as error:  # noqa: BLE001 - retry anything transient
            if attempt == attempts - 1:
                raise
            print(f'    retry {attempt + 1}: {error}', file=sys.stderr)
    return None


def pull_prices():
    """Every Pokemon price row, as (productId, finishIndex, market, low, high)."""
    groups = fetch_json(f'{BASE}/{POKEMON_CATEGORY}/groups')['results']
    print(f'{len(groups)} groups')

    rows = []
    for index, group in enumerate(groups, 1):
        group_id = group['groupId']
        try:
            payload = fetch_json(f'{BASE}/{POKEMON_CATEGORY}/{group_id}/prices')
        except Exception as error:  # noqa: BLE001
            print(f'  ! group {group_id} failed: {error}', file=sys.stderr)
            continue
        for row in payload.get('results', []):
            finish = FINISH_INDEX.get(row.get('subTypeName'))
            if finish is None:
                continue
            rows.append((
                int(row['productId']),
                finish,
                row.get('marketPrice'),
                row.get('lowPrice'),
                row.get('highPrice'),
            ))
        if index % 40 == 0:
            print(f'  {index}/{len(groups)} groups, {len(rows)} rows')
    return rows


def write_prices(rows, path):
    """Market/low/high per (product, finish), sorted for a compact delta."""
    rows.sort()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    for product_id, finish, market, low, high in rows:
        writer.writerow([
            product_id,
            finish,
            '' if market is None else f'{market:.2f}',
            '' if low is None else f'{low:.2f}',
            '' if high is None else f'{high:.2f}',
        ])
    text = buffer.getvalue().encode()
    with open(path, 'wb') as handle:
        handle.write(text)
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='app/assets')
    parser.add_argument('--archive', default='archive')
    parser.add_argument('--allow-short', action='store_true',
                        help='publish even if the row count looks wrong')
    args = parser.parse_args()

    today = dt.datetime.now(dt.timezone.utc)
    rows = pull_prices()

    priced = sum(1 for row in rows if row[2] is not None)
    null_share = 1 - (priced / max(len(rows), 1))
    print(f'\n{len(rows)} rows, {priced} priced ({null_share:.1%} without a price)')

    if not args.allow_short:
        if len(rows) < MIN_ROWS:
            sys.exit(f'REFUSING: only {len(rows)} rows, expected >= {MIN_ROWS}. '
                     'A truncated pull silently zeroes collections.')
        if null_share > MAX_NULL_SHARE:
            sys.exit(f'REFUSING: {null_share:.1%} of rows have no price.')

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.archive, exist_ok=True)

    stamp = today.strftime('%Y-%m-%d')
    price_path = os.path.join(args.out, 'prices.csv')
    text = write_prices(rows, price_path)

    # Archive the normalised rows forever: they are what value-over-time charts
    # are built from, and a gap there is permanent.
    with gzip.open(os.path.join(args.archive, f'prices-{stamp}.csv.gz'), 'wb') as handle:
        handle.write(text)

    manifest = {
        'latest': stamp,
        'prices': {
            'file': 'prices.csv',
            'sha256': hashlib.sha256(text).hexdigest(),
            'bytes': len(text),
            'rows': len(rows),
        },
        # Per source, not per sync: the USD figures are about an hour old at
        # publish time and any EUR figures would be far older, so a single
        # timestamp would be wrong for one of them.
        'sources': {
            'tcgplayer_usd': today.replace(microsecond=0).isoformat(),
        },
    }
    with open(os.path.join(args.out, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=1)

    print(f'  {price_path}  {len(text) / 1024 / 1024:.2f} MB '
          f'({len(gzip.compress(text)) / 1024:.0f} KB gzipped)')
    print(f'  archived prices-{stamp}.csv.gz')


if __name__ == '__main__':
    main()
