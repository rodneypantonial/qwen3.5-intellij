"""mitmproxy addon: removes <think>...</think> blocks from Ollama responses.

Handles /api/chat and /api/generate (JSON or NDJSON stream) and
/v1/chat/completions (JSON or SSE stream). Also asks Ollama to skip thinking.
"""
import json
import re

from mitmproxy import http


class Stripper:
    def __init__(self):
        self.in_think = False
        self.started = False

    def feed(self, text):
        if not text:
            return text
        out = ""
        while text:
            if self.in_think:
                end = text.find("</think>")
                if end < 0:
                    return out
                text = text[end + len("</think>"):]
                self.in_think = False
                continue
            start = text.find("<think>")
            if start < 0:
                out += text
                break
            out += text[:start]
            text = text[start + len("<think>"):]
            self.in_think = True
        if not self.started:
            out = out.lstrip()
            self.started = bool(out)
        return out


def _slots(obj):
    """(container, key) pairs holding generated text in a response object."""
    out = []
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        out.append((msg, "content"))
    if isinstance(obj.get("response"), str):
        out.append((obj, "response"))
    for ch in obj.get("choices") or []:
        for key in ("message", "delta"):
            part = ch.get(key)
            if isinstance(part, dict) and isinstance(part.get("content"), str):
                out.append((part, "content"))
        if isinstance(ch.get("text"), str):
            out.append((ch, "text"))
    return out


def _fix_obj(obj, s):
    for container, key in _slots(obj):
        container[key] = s.feed(container[key])
    return obj


COMMIT_RE = re.compile(r"commit\s+message", re.IGNORECASE)

COMMIT_RULES = """Format the commit message as a GitHub-style git commit message:
- Line 1: a summary in the imperative mood (e.g. "Add", "Fix", "Update"), at most 72 characters, capitalized, no trailing period.
- Line 2: blank.
- Then an optional body wrapped at 72 characters: short "- " bullet points explaining what changed and why.
Output ONLY the commit message: no code fences, no quotes, no preamble, no explanations,
no separator lines (such as "---" or "===") and no Markdown headings."""

RULE_RE = re.compile(r"^\s*([-=_*~])(\s*\1){2,}\s*$")

SUBJECT_MAX = 72
BODY_MAX = 72
COMMIT_MAX_TOKENS = 256
COMMIT_REPEAT_PENALTY = 1.1


def _texts(body):
    parts = [body.get("prompt"), body.get("system")]
    for m in body.get("messages") or []:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        parts.append(c)
    return " ".join(p for p in parts if isinstance(p, str))


def _wrap(line, width):
    indent = "  " if line.startswith(("- ", "* ")) else ""
    words, lines, cur = line.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = indent + w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return lines or [""]


def format_commit(text):
    """Normalize model output into a GitHub-style commit message."""
    text = text.strip()
    text = re.sub(r"^```[\w-]*\s*\n?|\n?```\s*$", "", text).strip()
    text = re.sub(r"^(commit message|subject)\s*:\s*", "", text, flags=re.IGNORECASE)
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return text
    subject = re.sub(r"^(summary|title)\s*:\s*", "", lines[0].strip(), flags=re.IGNORECASE)
    subject = subject.strip("`\"'* #").rstrip(".")
    if len(subject) > SUBJECT_MAX:
        cut = subject[:SUBJECT_MAX + 1].rsplit(" ", 1)[0]
        subject = cut[:SUBJECT_MAX].rstrip(" ,;:-")
    if subject and subject[0].islower() and ":" not in subject.split(" ")[0]:
        subject = subject[0].upper() + subject[1:]
    body = [l for l in lines[1:] if not RULE_RE.match(l)]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    wrapped = []
    for l in body:
        l = re.sub(r"^\s*[*\u2022]\s+", "- ", l)
        wrapped.extend(_wrap(l, BODY_MAX) if l.strip() else [""])
    return subject + ("\n\n" + "\n".join(wrapped) if wrapped else "")


def is_valid_commit(msg):
    lines = msg.split("\n")
    if not lines[0].strip() or len(lines[0]) > SUBJECT_MAX or lines[0].endswith("."):
        return False
    if len(lines) > 1 and (lines[1] != "" or len(lines) < 3):
        return False
    return (all(len(l) <= BODY_MAX and not RULE_RE.match(l) for l in lines[2:])
            and "```" not in msg)


def request(flow: http.HTTPFlow):
    path = flow.request.path
    if flow.request.method != "POST" or not path.startswith(
            ("/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions")):
        return
    try:
        body = json.loads(flow.request.get_text())
    except Exception:
        return
    if path.startswith(("/api/chat", "/api/generate")):
        body.setdefault("think", False)
    if COMMIT_RE.search(_texts(body)):
        flow.metadata["commit"] = True
        if path.startswith(("/api/chat", "/api/generate")):
            opts = body.setdefault("options", {})
            opts.setdefault("num_predict", COMMIT_MAX_TOKENS)
            opts.setdefault("repeat_penalty", COMMIT_REPEAT_PENALTY)
        else:
            body.setdefault("max_tokens", COMMIT_MAX_TOKENS)
            body.setdefault("frequency_penalty", 0.3)
        if isinstance(body.get("messages"), list):
            body["messages"].append({"role": "system", "content": COMMIT_RULES})
        elif isinstance(body.get("prompt"), str):
            if path.startswith("/api/generate"):
                body["system"] = ((body.get("system") or "") + "\n\n" + COMMIT_RULES).strip()
            else:
                body["prompt"] = COMMIT_RULES + "\n\n" + body["prompt"]
    flow.request.set_text(json.dumps(body))


def response(flow: http.HTTPFlow):
    path = flow.request.path
    if not path.startswith(("/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions")):
        return
    text = flow.response.get_text()
    if not text:
        return
    s = Stripper()
    try:
        objs = [("", _fix_obj(json.loads(text), s))]
        single = True
    except ValueError:
        single = False
        objs = []
        for line in text.split("\n"):
            prefix, payload = ("data: ", line[6:]) if line.startswith("data: ") else ("", line)
            try:
                objs.append((prefix, _fix_obj(json.loads(payload), s)))
            except ValueError:
                objs.append((None, line))
    if flow.metadata.get("commit") and flow.response.status_code == 200:
        slots = [sl for p, o in objs if p is not None for sl in _slots(o)]
        if slots:
            msg = format_commit("".join(c[k] for c, k in slots))
            for i, (c, k) in enumerate(slots):
                c[k] = msg if i == 0 else ""
            flow.response.headers["X-Commit-Format"] = "valid" if is_valid_commit(msg) else "invalid"
    if single:
        flow.response.set_text(json.dumps(objs[0][1]))
    else:
        flow.response.set_text("\n".join(o if p is None else p + json.dumps(o) for p, o in objs))
