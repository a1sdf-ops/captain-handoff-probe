#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated probe for Chatwoot Captain's "handoff judgment".

Reproduces the decision surface of Captain::ConversationCompletionService
(does an inactive conversation count as COMPLETE, or should it be handed off
to a human?) without deploying the Rails stack.

Fidelity notes (honest boundaries):
  Taken verbatim from upstream
    - prompt      : chatwoot/enterprise/lib/captain/prompts/conversation_completion.liquid
    - schema      : {complete: boolean, reason: string}
    - call shape  : system = prompt, user = transcript, structured output via tool call
  Re-implemented (our equivalent, not upstream code)
    - transcript assembly: label + content per message (equivalent to upstream's
      format_evaluation_input / message_sender_label result)
  Known deviations (do not affect the judgment itself)
    - plain HTTP instead of the RubyLLM/Rails stack (no Ruby on this machine)
    - temperature fixed at 0 (upstream leaves it to the RubyLLM default)
    - no quota / instrumentation wrapper (upstream also does not bill this call)

Usage:
  python probe.py                                  # baseline (upstream prompt)
  PROBE_MODEL=qwen-turbo python probe.py           # cross-model comparison
  PROBE_PROMPT=./variants/v1.liquid python probe.py

Env:
  PROBE_ENVFILE   path to a .env holding LLM_BASE_URL / DASHSCOPE_API_KEY
                  (default: ./.env next to this file)
  CAPTAIN_CLONE   path to the chatwoot clone (default: ../chatwoot)
  PROBE_MODEL     model id (default: from .env LLM_MODEL, else qwen-plus)
  PROBE_PROMPT    prompt file to use (default: upstream prompt from the clone)
  PROBE_TEMPERATURE  default 0
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CLONE = os.environ.get("CAPTAIN_CLONE") or os.path.abspath(os.path.join(HERE, "..", "chatwoot"))
DEFAULT_PROMPT = os.path.join(CLONE, "enterprise/lib/captain/prompts/conversation_completion.liquid")
SAMPLES = os.path.join(HERE, os.environ.get("PROBE_SAMPLES", "samples.json"))
ENVFILE = os.environ.get("PROBE_ENVFILE", os.path.join(HERE, ".env"))
RESULTS = os.path.join(HERE, "results")


def load_env(path):
    d = {}
    if not os.path.exists(path):
        return d
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


ENV = {**load_env(ENVFILE), **os.environ}
BASE = (ENV.get("LLM_BASE_URL") or "").rstrip("/")
KEY = ENV.get("DASHSCOPE_API_KEY") or ENV.get("OPENAI_API_KEY")
MODEL = ENV.get("PROBE_MODEL", ENV.get("LLM_MODEL", "qwen-plus"))
TEMPERATURE = float(ENV.get("PROBE_TEMPERATURE", "0"))

TOOL = {
    "type": "function",
    "function": {
        "name": "record_evaluation",
        "description": "Record whether the conversation is complete and can be closed, with a brief reason.",
        "parameters": {
            "type": "object",
            "properties": {
                "complete": {"type": "boolean", "description": "Whether the conversation is complete and can be closed"},
                "reason": {"type": "string", "description": "Brief explanation"},
            },
            "required": ["complete", "reason"],
        },
    },
}


def build_input(sample):
    lines = ["%s: %s" % (m["label"], m["content"]) for m in sample["messages"]]
    return "Conversation status: %s\n\nConversation transcript:\n%s" % (sample["status"], "\n".join(lines))


def call(system, user):
    body = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": [TOOL],
        "tool_choice": {"type": "function", "function": {"name": "record_evaluation"}},
    }
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % KEY},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    tc = msg.get("tool_calls")
    if tc:
        return json.loads(tc[0]["function"]["arguments"])
    m = re.search(r"\{.*\}", msg.get("content") or "", re.S)
    if m:
        return json.loads(m.group(0))
    return {"complete": None, "reason": "PARSE_FAIL: " + (msg.get("content") or "")[:150]}


def main():
    if not BASE or not KEY:
        sys.exit("missing LLM_BASE_URL / DASHSCOPE_API_KEY; set them in %s or the environment" % ENVFILE)

    prompt_path = os.environ.get("PROBE_PROMPT", DEFAULT_PROMPT)
    if not os.path.exists(prompt_path):
        sys.exit("prompt not found: %s\n(clone chatwoot as a sibling dir or set CAPTAIN_CLONE)" % prompt_path)

    system = open(prompt_path, encoding="utf-8").read()
    samples = json.load(open(SAMPLES, encoding="utf-8"))

    print("prompt = %s" % prompt_path)
    print("model  = %s   temp = %s" % (MODEL, TEMPERATURE))
    print("-" * 78)
    hit = 0
    rows = []
    for s in samples:
        got = call(system, build_input(s))
        got_label = "complete" if got.get("complete") else ("incomplete" if got.get("complete") is False else "?")
        ok = got_label == s["expect"]
        hit += ok
        rows.append((s["id"], s["expect"], got_label, ok, s["topic"], got.get("reason")))
        print("%s %-3s expect=%-10s got=%-10s | %s" % ("OK " if ok else "XX ", s["id"], s["expect"], got_label, s["topic"]))
        print("        reason: %s" % got.get("reason"))
    print("-" * 78)
    print("agreement %d/%d" % (hit, len(samples)))

    os.makedirs(RESULTS, exist_ok=True)
    tag = os.environ.get("PROBE_TAG") or MODEL
    out = os.path.join(RESULTS, "%s.json" % tag)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {"model": MODEL, "temperature": TEMPERATURE, "prompt": os.path.relpath(prompt_path, HERE),
             "agreement": "%d/%d" % (hit, len(samples)),
             "rows": [{"id": r[0], "expect": r[1], "got": r[2], "ok": r[3], "topic": r[4], "reason": r[5]} for r in rows]},
            f, ensure_ascii=False, indent=2)
    print("result written: %s" % os.path.relpath(out, HERE))


if __name__ == "__main__":
    main()
