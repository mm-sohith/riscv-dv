#!/usr/bin/env python3
"""
spike.py -- Patch a RISC-V .S file with a signature dump loop + self-check,
            and optionally embed Spike reference data.

Pass 1 (no signature): inject dump loop + self-check scaffold, compile, run Spike
Pass 2 (with signature): restore original, re-inject + embed _spike_ref_start data

Transformations
---------------
1.  la xN, test_done   ->   la xN, _pre_done   (any xN register)

2.  Before test_done: label, insert:

        _pre_done:
            <dump loop>      -- ld every 8-byte word from begin_signature..end_signature
                             -- into t0; visible in waveform / Spike log
            <self-check>     -- compare RTL signature against _spike_ref_start word by word
                             -- PASS -> test_done, FAIL -> test_fail

3.  After test_done's ecall, insert:

        test_fail:
            li gp, 0
            ecall

4.  (Pass 2 only) Append .data.ref section with _spike_ref_start words at EOF.

Usage
-----
    python3 spike.py <input.s>                   # Pass 1 -- patch only
    python3 spike.py <input.s> <spike.sig.hex>   # Pass 2 -- patch + embed ref data
"""

import sys
import re

# --------------------------------------------------------------------------- #
# Block injected BEFORE test_done:
# --------------------------------------------------------------------------- #
INJECT_BEFORE_TEST_DONE = """
_pre_done:
# -------------------------------------------------------
# Phase 1 -- Signature dump loop
# Loads every 8-byte doubleword from begin_signature to
# end_signature into t0 sequentially.
# Each value is visible on the register bus (waveform/log).
# -------------------------------------------------------
.section .text
.globl _pre_done
    la   t1, begin_signature     # t1 = current read pointer
    la   t2, end_signature       # t2 = one-past-end pointer

_dump_loop:
    bge  t1, t2, _dump_done      # finished all entries -> self-check
    ld   t0, 0(t1)               # load 8-byte word into t0 (visible in waveform)
    addi t1, t1, 8               # advance pointer by 8 bytes
    j    _dump_loop

_dump_done:

# -------------------------------------------------------
# Phase 2 -- Self-check loop
# Compares [begin_signature, end_signature) word-by-word
# against the embedded _spike_ref_start reference array.
# PASS -> jumps to test_done, FAIL -> jumps to test_fail.
# -------------------------------------------------------
    la   a0, begin_signature     # a0 = RTL result pointer
    la   a1, end_signature       # a1 = one-past-end
    la   a2, _spike_ref_start    # a2 = Spike reference pointer

_check_loop:
    bge  a0, a1, _check_pass     # exhausted all entries -> PASS

    ld   t0, 0(a0)               # RTL result doubleword
    ld   t1, 0(a2)               # Spike reference doubleword
    bne  t0, t1, _check_fail     # mismatch -> FAIL

    addi a0, a0, 8               # advance RTL pointer
    addi a2, a2, 8               # advance ref pointer
    j    _check_loop

_check_pass:
    li   gp, 1                   # PASS marker
    j    test_done

_check_fail:
    li   gp, 0xff                 # FAIL marker
    j    test_fail

"""


# --------------------------------------------------------------------------- #
# Block injected AFTER test_done's ecall:
# --------------------------------------------------------------------------- #
INJECT_AFTER_TEST_DONE = """
test_fail:
                  li gp, 0xff
                  ecall

"""

WORDS_PER_LINE = 8


# --------------------------------------------------------------------------- #
# sig2asm: parse a Spike hex signature, return .data.ref section lines
# Each signature line is a 64-bit hex value; split into lo/hi 32-bit words.
# --------------------------------------------------------------------------- #
def sig2asm(sig_file):
    words = []
    with open(sig_file) as f:
        for line in f:
            line = line.strip()
            if line == '' or line.startswith('#'):
                continue
            val = int(line, 16)
            lo  = val & 0xFFFFFFFF
            hi  = (val >> 32) & 0xFFFFFFFF
            words.append(lo)
            words.append(hi)

    out = []
    out.append("\n# Auto-generated Spike reference data -- do not edit\n")
    out.append(".section .data.ref,\"aw\",@progbits\n")
    out.append(".align 6\n")
    out.append(".global _spike_ref_start\n")
    out.append("_spike_ref_start:\n")

    for i in range(0, len(words), WORDS_PER_LINE):
        chunk     = words[i : i + WORDS_PER_LINE]
        word_strs = ", ".join("0x{:08x}".format(w) for w in chunk)
        out.append(".word {}\n".format(word_strs))

    out.append(".global _spike_ref_end\n")
    out.append("_spike_ref_end:\n")

    return out


# --------------------------------------------------------------------------- #
# patch: apply label rewrite + block injections
# --------------------------------------------------------------------------- #
def patch(lines):
    out = []

    inject_block = INJECT_BEFORE_TEST_DONE

    re_la_test_done    = re.compile(r'^(.*\bla\s+x[0-9]+\s*,\s*)test_done(\s*(?:#.*)?)$')
    re_test_done_label = re.compile(r'^(\s*test_done\s*:)')
    re_ecall           = re.compile(r'^\s+ecall\s*(?:#.*)?$')

    inserted_pre_done  = False
    inserted_test_fail = False
    inside_test_done   = False

    for line in lines:
        # 1. Rewrite  la xN, test_done  ->  la xN, _pre_done
        m = re_la_test_done.match(line)
        if m:
            line = m.group(1) + '_pre_done' + m.group(2) + '\n'

        # 2. Inject _pre_done block before test_done:
        if not inserted_pre_done and re_test_done_label.match(line):
            out.append(inject_block)
            inserted_pre_done = True
            inside_test_done  = True
            out.append(line)
            continue

        # 3. Inject test_fail after test_done's ecall
        if inside_test_done and not inserted_test_fail and re_ecall.match(line):
            out.append(line)
            out.append(INJECT_AFTER_TEST_DONE)
            inserted_test_fail = True
            inside_test_done   = False
            continue

        out.append(line)

    if not inserted_pre_done:
        print("WARNING: 'test_done:' label not found -- no block injected.", file=sys.stderr)
    if not inserted_test_fail:
        print("WARNING: ecall after 'test_done:' not found -- test_fail not added.", file=sys.stderr)

    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        print("Usage: {} <input.s> [spike.sig.hex]".format(sys.argv[0]))
        sys.exit(1)

    src      = sys.argv[1]
    sig_file = sys.argv[2] if len(sys.argv) >= 3 else None
    is_pass2 = sig_file is not None

    with open(src, 'r', errors='replace') as f:
        lines = f.readlines()

    if is_pass2:
        print("Pass 2: appending _spike_ref_start from: {}".format(sig_file))
    else:
        print("Pass 1: patch only, no ref data")

    patched = patch(lines)

    # Pass 2 only: embed _spike_ref_start data at EOF
    if is_pass2:
        ref_lines = sig2asm(sig_file)
        patched.extend(ref_lines)

    with open(src, 'w') as f:
        f.writelines(patched)

    print("Done. Patched in-place: {}".format(src))


if __name__ == '__main__':
    main()