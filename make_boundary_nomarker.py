#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the no-marker control for the episode-boundary experiment.

The handoff judge's transcript builder filters to message_type IN (incoming,
outgoing), so in production the `<conversation_boundary status="resolved" />`
marker NEVER reaches it (only the assistant's history builder includes activity
messages). This script strips the marker so we can compare:

  samples_boundary.json           -> judge sees the marker   (counterfactual)
  samples_boundary_nomarker.json  -> judge does not          (matches production)

Usage:  python make_boundary_nomarker.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "samples_boundary.json")
DST = os.path.join(HERE, "samples_boundary_nomarker.json")
MARKER = '<conversation_boundary status="resolved" />'

with open(SRC, encoding="utf-8") as f:
    samples = json.load(f)

stripped = 0
for s in samples:
    kept = [m for m in s["messages"] if m["content"] != MARKER]
    stripped += len(s["messages"]) - len(kept)
    s["messages"] = kept

with open(DST, "w", encoding="utf-8") as f:
    json.dump(samples, f, ensure_ascii=False, indent=2)

print("wrote %s (stripped %d marker lines)" % (os.path.basename(DST), stripped))
