#!/usr/bin/env python3
"""
extract_dump.py -- Extract _dump_loop ld values from a Spike log
                   and produce a signature file matching Spike's format.

Each committed `ld t0` inside the _dump_loop section produces one line:
    <16-char hex>   (64-bit value, no 0x prefix, lowercase)

Usage
-----
    python3 extract_dump.py <spike.log> <output.signature>
    python3 extract_dump.py <spike.log>          # prints to stdout
"""

import sys
import re

# Matches a committed ld t0 line with a memory access, e.g.:
# core   0: 3 0x0000000080004670 (0x00033283) x5  0x8d9300000d970062 mem 0x...
#
# Groups: (64-bit hex value in x5)
RE_LD_COMMIT = re.compile(
    r'core\s+\d+:\s+3\s+0x[0-9a-fA-F]+\s+\(0x[0-9a-fA-F]+\)\s+'
    r'x5\s+(0x[0-9a-fA-F]+)\s+mem\s+0x[0-9a-fA-F]+'
)

# Marks entry into _dump_loop region
RE_DUMP_LOOP_ENTER = re.compile(r'>>>>\s+_dump_loop')

# Marks exit — _dump_done label means loop is over
RE_DUMP_DONE = re.compile(r'>>>>\s+_dump_done')


def extract(log_path):
    values = []
    in_dump_loop = False

    with open(log_path, 'r', errors='replace') as f:
        for line in f:
            # Enter dump loop region
            if RE_DUMP_LOOP_ENTER.search(line):
                in_dump_loop = True
                continue

            # Exit when _dump_done is reached
            if in_dump_loop and RE_DUMP_DONE.search(line):
                break

            if not in_dump_loop:
                continue

            # Capture each committed ld t0 value
            m = RE_LD_COMMIT.search(line)
            if m:
                val = int(m.group(1), 16)
                values.append(val)

    return values


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <spike.log> [output.signature]")
        sys.exit(1)

    log_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) >= 3 else None

    values = extract(log_path)

    if not values:
        print("WARNING: No ld t0 commits found in _dump_loop region.", file=sys.stderr)
        sys.exit(1)

    # Format: one 64-bit hex value per line, 16 chars, no 0x prefix
    # This matches Spike's own signature output format
    lines = [f"{v:016x}\n" for v in values]

    if out_path:
        with open(out_path, 'w') as f:
            f.writelines(lines)
        print(f"Written {len(values)} entries to: {out_path}")
    else:
        sys.stdout.writelines(lines)


if __name__ == '__main__':
    main()