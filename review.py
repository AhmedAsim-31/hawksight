import json
import re

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "hawksight"
SEVERITIES = ("P0", "P1", "P2")
FINDING_RE = re.compile(r"<!-- hawksight:finding (\{.*?\}) -->")
TASK = """TASK:
1. For each existing finding, decide its status: "fixed" if the current code no longer has the problem, "rebutted" if the author's reply convincingly shows it is not a problem, otherwise "open". Write a one-line reply to the author when the status is not "open" or the author replied; otherwise write "-".
2. List new problems. Never repeat an existing finding. Each needs the file path, a line number taken from the numbered diff, a severity, a short title, and a markdown body that explains what goes wrong and shows the fix once.
   Severity:
   - P0 (Critical): security vulnerabilities (SQL injection, XSS, exposed tokens or keys), data loss, crashes on a main path.
   - P1 (Important): logic errors, race conditions (check-then-act), unawaited promises, missing edge-case handling.
   - P2 (Minor): small bugs, redundant code, maintainability issues. Never style a formatter or linter enforces.
   Diff lines starting with "-" are removed code: never report them as the current state.
   Never flag a deliberate removal, a wording or grammar preference, or something you admit is not a bug.
3. Write a two-sentence summary of what the PR does and its main risk.

Answer in exactly this format and nothing else:

### SUMMARY
<two sentences>

### EXISTING F1
status: fixed|rebutted|open
reply: <one line or ->

### FINDING
path: <file path>
line: <number>
severity: P0|P1|P2
title: <short title>
body:
<markdown explanation and fix>

Repeat the EXISTING block once per existing finding and the FINDING block once per new problem. Write no FINDING block if there are no new problems."""


def parse_output(text):
    """Parse the tagged plain-text answer; free text avoids the repetition loops JSON-constrained decoding caused."""
    out = {"summary": "", "existing": [], "new": []}
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        head, _, rest = block.partition("\n")
        kind = head.split()
        if kind[:1] == ["SUMMARY"]:
            out["summary"] = rest.strip()
        elif kind[:1] == ["EXISTING"] and len(kind) > 1:
            fields, _ = _fields(rest)
            if fields.get("status") in ("fixed", "rebutted", "open"):
                reply = fields.get("reply", "")
                out["existing"].append({"id": kind[1], "status": fields["status"], "reply": "" if reply == "-" else reply})
        elif kind[:1] == ["FINDING"]:
            # The model sometimes drops the header between findings, so each "path:" line also starts one.
            for chunk in re.split(r"^(?=path:)", rest, flags=re.M):
                fields, body = _fields(chunk)
                if fields.get("line", "").isdigit() and fields.get("severity") in SEVERITIES:
                    out["new"].append({"path": fields.get("path", "").strip("`"), "line": int(fields["line"]),
                                       "severity": fields["severity"], "title": fields.get("title", ""), "body": body})
    return out


def _fields(chunk):
    m = re.search(r"^body:\s*$", chunk, re.M)
    head, body = (chunk[:m.start()], chunk[m.end():]) if m else (chunk, "")
    fields = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    return fields, body.strip()


def number_diff(diff):
    """Prefix each new-file line with its line number; returns the text and the commentable lines per path."""
    out, valid, path, n = [], {}, None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            valid.setdefault(path, set())
            out.append(line)
        elif line.startswith("@@"):
            n = int(re.search(r"\+(\d+)", line).group(1))
            out.append(line)
        elif path and line[:1] in ("+", " "):
            valid[path].add(n)
            out.append(f"{n:>5} {line}")
            n += 1
        else:
            out.append(f"      {line}")
    valid.pop(None, None)
    return "\n".join(out), valid


def score(open_severities):
    """5 only when nothing is open; any P0 caps it at 2, two or more at 1."""
    p0 = open_severities.count("P0")
    if p0:
        return 1 if p0 > 1 else 2
    if "P1" in open_severities:
        return 3
    return 4 if open_severities else 5


def build_prompt(context, numbered_diff, existing):
    items = []
    for e in existing:
        replies = "\n".join(f"    Author reply: {r}" for r in e["replies"]) or "    (no author reply)"
        items.append(f"[{e['id']}] {e['severity']} {e['path']}:{e['line']} {e['title']}\n{e['body']}\n{replies}")
    ids = ", ".join(e["id"] for e in existing)
    required = (f"\nWrite one EXISTING block for each of {ids}, and do not list any of them again as a FINDING."
                if existing else "")
    return f"""REPOSITORY CONTEXT:
{context}

=========================================
PULL REQUEST DIFF (new-file line numbers on the left; removed lines have none):
{numbered_diff}

=========================================
EXISTING FINDINGS FROM YOUR EARLIER REVIEWS:
{chr(10).join(items) or "None."}

{TASK}{required}"""


def run_model(prompt):
    # Thinking mode can spend the whole output budget reasoning before it writes the review.
    r = requests.post(OLLAMA_URL, timeout=1800, json={"model": MODEL, "prompt": prompt, "stream": False,
                                                      "think": False})
    r.raise_for_status()
    data = r.json()
    if data.get("done_reason") == "length":
        raise RuntimeError("model hit the output limit (likely a repetition loop)")
    out = parse_output(data["response"])
    if not out["summary"]:
        # An unparseable answer would otherwise post as a clean 5/5.
        raise RuntimeError(f"model ignored the output format: {data['response'][:300]!r}")
    return out


def finding_body(f):
    meta = json.dumps({"severity": f["severity"], "title": f["title"]})
    return f"**{f['severity']}** · {f['title']}\n\n{f['body']}\n\n<!-- hawksight:finding {meta} -->"


def parse_finding(body):
    m = FINDING_RE.search(body or "")
    return json.loads(m.group(1)) if m else None


def bot(text):
    return f"{text}\n\n<!-- hawksight -->"


def summary_body(summary, value, threads, sha):
    open_ = [t["severity"] for t in threads if not t["resolved"]]
    counts = " · ".join(f"{open_.count(s)} {s}" for s in SEVERITIES)
    rows = "\n".join(
        f"| {t['severity']} | [{t['title']}]({t['url']}) `{t['path']}` | {'✅ resolved' if t['resolved'] else '🔴 open'} |"
        for t in sorted(threads, key=lambda t: (t["resolved"], t["severity"])))
    table = f"| Severity | Finding | Status |\n|---|---|---|\n{rows}" if rows else "No findings."
    return f"""<!-- hawksight:summary -->
### 🦅 hawksight review

**Score: {value}/5** · open: {counts} · reviewed `{sha[:7]}`

{summary}

{table}

<sub>5/5 needs every finding resolved and no new ones. Reply in a finding's thread to discuss it; push a commit or comment `/hawksight` to re-review.</sub>"""


if __name__ == "__main__":
    text, valid = number_diff("+++ b/a.py\n@@ -1,2 +10,3 @@\n ctx\n-old\n+new\n+more\n")
    assert valid == {"a.py": {10, 11, 12}}, valid
    assert "   11 +new" in text, text
    assert [score(s) for s in ([], ["P2"], ["P1", "P2"], ["P0"], ["P0", "P0"])] == [5, 4, 3, 2, 1]
    body = finding_body({"severity": "P1", "title": "Off-by-one", "body": "Use `<`."})
    assert parse_finding(body) == {"severity": "P1", "title": "Off-by-one"}
    assert parse_finding("plain comment") is None
    parsed = parse_output("<think></think>### SUMMARY\nAdds X.\n\n### EXISTING F1\nstatus: rebutted\nreply: Agreed, style rule.\n\n"
                          "### FINDING\npath: `a.py`\nline: 11\nseverity: P1\ntitle: Bug\nbody:\nUse `<`.\n\n```py\nx: 1\n```\n")
    assert parsed == {"summary": "Adds X.", "existing": [{"id": "F1", "status": "rebutted", "reply": "Agreed, style rule."}],
                      "new": [{"path": "a.py", "line": 11, "severity": "P1", "title": "Bug",
                               "body": "Use `<`.\n\n```py\nx: 1\n```"}]}, parsed
    print("ok")
