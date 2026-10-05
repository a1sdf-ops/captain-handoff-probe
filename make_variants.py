#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the ablation prompts for the handoff-judgment probe.

These are *derived* files: they edit the upstream prompt at runtime. They are
NOT committed (see .gitignore) because the upstream prompt lives under
Chatwoot's commercially licensed enterprise/ directory. Running this script
only edits your local clone's copy; nothing here redistributes it.

Ablation ladder (each step from the previous level, except v3 which restarts
from the upstream prompt):
  v1  remove every "a handoff is not a resolution" criterion
  v2  v1 + flip the global bias sentence from "keep OPEN" to "close"
  v3  remove the entire INCOMPLETE criterion block + neutral bias
  v4  v3 + loosen the positive COMPLETE definition

Usage:  python make_variants.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CLONE = os.environ.get("CAPTAIN_CLONE") or os.path.abspath(os.path.join(HERE, "..", "chatwoot"))
SRC = os.path.join(CLONE, "enterprise/lib/captain/prompts/conversation_completion.liquid")
OUT = os.path.join(HERE, "variants")

BIAS_OPEN = ("When in doubt, keep the conversation OPEN. It is far better to hand off to a human agent "
             "unnecessarily than to close a conversation where the customer still needs help.")
BIAS_CLOSE_SOFT = ("When in doubt, close the conversation. It is acceptable to close a case once the customer's "
                   "immediate question has been answered, even if a follow-up might later be needed.")
BIAS_CLOSE_HARD = "When in doubt, close the conversation."

V1_MARKERS = [
    "said it handed off, will hand off, escalated",
    "promised future action or follow-up instead of resolving",
    "Important handoff rule:",
    "A handoff, escalation, transfer, acknowledgement, or promise of future follow-up is not a resolution",
    "If conversation status is \"pending\" and Captain/Bot/Assistant says it handed off",
]

INCOMPLETE_HEADER = "A conversation is INCOMPLETE (keep open) if ANY of these apply:"
RESUME_AT = "Do NOT treat these as incomplete by themselves:"

V4_EDITS = [
    ("A conversation is COMPLETE only if ALL of these are true:",
     "A conversation is COMPLETE if the assistant has responded to the customer's latest request:"),
    ("- There are no unanswered questions, unmet requests, or outstanding follow-ups from either side\n", ""),
]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(name, text):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(text)
    print("  wrote %s (%d chars)" % (name, len(text)))


def v1(upstream):
    kept, removed = [], 0
    for line in upstream.splitlines(keepends=True):
        if any(m in line for m in V1_MARKERS):
            removed += 1
            continue
        kept.append(line)
    assert removed == len(V1_MARKERS), "expected to remove %d lines, got %d (upstream changed?)" % (len(V1_MARKERS), removed)
    return "".join(kept)


def v3(upstream):
    out, removing = [], False
    for line in upstream.splitlines(keepends=True):
        if INCOMPLETE_HEADER in line:
            removing = True
            continue
        if removing and RESUME_AT in line:
            removing = False
            out.append(line)
            continue
        if removing:
            continue
        out.append(line)
    text = "".join(out)
    assert BIAS_OPEN in text
    return text.replace(BIAS_OPEN, BIAS_CLOSE_HARD)


def main():
    if not os.path.exists(SRC):
        raise SystemExit("upstream prompt not found: %s\n(clone chatwoot as a sibling dir or set CAPTAIN_CLONE)" % SRC)
    os.makedirs(OUT, exist_ok=True)
    upstream = read(SRC)

    t1 = v1(upstream)
    write("v1_no_handoff.liquid", t1)

    assert BIAS_OPEN in t1
    write("v2_bias_flipped.liquid", t1.replace(BIAS_OPEN, BIAS_CLOSE_SOFT))

    t3 = v3(upstream)
    write("v3_lenient.liquid", t3)

    t4 = t3
    for old, new in V4_EDITS:
        assert old in t4, "v4 edit target missing: %r" % old[:60]
        t4 = t4.replace(old, new)
    write("v4_weak_complete.liquid", t4)

    print("done. run:  PROBE_PROMPT=./variants/v1_no_handoff.liquid python probe.py")


if __name__ == "__main__":
    main()
