import os
import sys
from urllib.parse import quote

INPUT = r"ag land with house.csv"
BACKUP = INPUT + ".bak"

# Helpers to detect separator rows and split/format cells

def is_sep_line(line: str) -> bool:
    s = line.strip()  # keep leading/trailing for check below
    if not s.startswith('|') or not s.endswith('|'):
        return False
    cells = [c.strip() for c in s.strip('|').split('|')]
    if not cells:
        return False
    # A separator line is composed of only dashes in all cells
    return all(len(c) > 0 and set(c) <= {'-'} for c in cells)


def is_data_line(line: str) -> bool:
    s = line.strip()
    if not (s.startswith('|') and s.endswith('|')):
        return False
    return not is_sep_line(line)


def split_cells(line: str):
    # Assumes a table row like: | cell1 | cell2 | ... |
    inner = line.strip()[1:-1]  # remove leading and trailing '|'
    parts = [p.strip() for p in inner.split('|')]
    return parts


def make_sep(widths):
    return '|' + '|'.join('-' * (w + 2) for w in widths) + '|'  # +2 for padding spaces


def make_row(values, widths):
    padded = []
    for v, w in zip(values, widths):
        s = (v if v is not None else '')
        padded.append(' ' + s.ljust(w) + ' ')
    return '|' + '|'.join(padded) + '|'


def build_zillow_url(parcel_address: str, municipality: str) -> str:
    addr_parts = []
    if parcel_address:
        addr_parts.append(parcel_address.strip())
    if municipality:
        addr_parts.append(municipality.strip())
    # Assuming NY as the state for this dataset
    addr_parts.append('NY')
    query = ', '.join([p for p in addr_parts if p])
    if not query:
        return ''
    return f"https://www.zillow.com/homes/{quote(query)}_rb/"


def main():
    if not os.path.exists(INPUT):
        print(f"File not found: {INPUT}", file=sys.stderr)
        sys.exit(1)

    with open(INPUT, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    # Extract header and data rows from the pretty table
    header = None
    data_rows = []

    for line in lines:
        if is_data_line(line):
            cells = split_cells(line)
            # First data-style line after a separator is header
            if header is None or header == [] or header == ['']:
                header = cells
            else:
                data_rows.append(cells)
        # ignore separator and any other lines

    if not header:
        print('Could not parse table header.', file=sys.stderr)
        sys.exit(1)

    # Normalize row lengths to header length
    col_count = len(header)
    norm_rows = []
    for r in data_rows:
        if len(r) < col_count:
            r = r + [''] * (col_count - len(r))
        elif len(r) > col_count:
            r = r[:col_count]
        norm_rows.append(r)

    header = header[:]  # copy

    # Append new column
    header.append('zillow_url')

    # Build URLs for each row
    try:
        idx_parcel = header.index('parcel_address')
    except ValueError:
        # In case header names have stray spaces
        try:
            idx_parcel = [h.strip() for h in header].index('parcel_address')
        except Exception:
            idx_parcel = None
    try:
        idx_muni = header.index('municipality')
    except ValueError:
        try:
            idx_muni = [h.strip() for h in header].index('municipality')
        except Exception:
            idx_muni = None

    out_rows = []
    for r in norm_rows:
        parcel = r[idx_parcel].strip() if (idx_parcel is not None and idx_parcel < len(r)) else ''
        muni = r[idx_muni].strip() if (idx_muni is not None and idx_muni < len(r)) else ''
        url = build_zillow_url(parcel, muni)
        out_rows.append(r + [url])

    # Compute column widths
    widths = [0] * len(header)
    for i, h in enumerate(header):
        widths[i] = max(widths[i], len(h.strip()))
    for r in out_rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len((v or '').strip()))

    # Compose new table
    sep = make_sep(widths)
    output_lines = []
    output_lines.append(sep)
    output_lines.append(make_row([h.strip() for h in header], widths))
    output_lines.append(sep)
    for r in out_rows:
        output_lines.append(make_row([ (v or '').strip() for v in r], widths))
        output_lines.append(sep)

    # Backup original and write
    if not os.path.exists(BACKUP):
        with open(BACKUP, 'w', encoding='utf-8') as bf:
            bf.write('\n'.join(lines) + ('\n' if lines and lines[-1] != '' else ''))
    with open(INPUT, 'w', encoding='utf-8') as wf:
        wf.write('\n'.join(output_lines) + '\n')

    print(f"Updated {INPUT} with zillow_url and saved backup to {BACKUP}")

if __name__ == '__main__':
    main()
