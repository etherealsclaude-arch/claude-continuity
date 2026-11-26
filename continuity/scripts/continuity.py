#!/usr/bin/env python3
"""continuity: per-project notes, transcript archive, context checkpoint, handoff.
Stdlib only. No network, no model calls. Run with -h for commands."""
import argparse, contextlib, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
CONF = Path(os.environ.get("CONTINUITY_CONF", HOME / ".config/continuity"))
STATE = Path(os.environ.get("CONTINUITY_STATE", HOME / ".local/state/continuity"))
SELF = Path(__file__).resolve()
DEFAULT_THRESHOLD = 70
STALE_LAUNCH_SEC = 600
MAX_HANDOFF_WORDS = 400
SECTIONS = ["Objective", "Latest user request", "Decisions", "Changed files",
            "Verified", "Blockers", "Next action", "Running operations"]

SECRET_RES = [re.compile(p, re.S) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    r"sk-[A-Za-z0-9_\-]{16,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}",
    r"AKIA[0-9A-Z]{16}", r"xox[abprs]-[A-Za-z0-9\-]{10,}", r"AIza[0-9A-Za-z_\-]{30,}",
    r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S{6,}",
)]


def redact(t):
    for r in SECRET_RES:
        t = r.sub("[REDACTED]", t)
    return t


def jload(p, d=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def jsave(p, obj):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1)); os.replace(tmp, p)


@contextlib.contextmanager
def lock(name, wait=5.0):
    d = STATE / "locks" / name; d.parent.mkdir(parents=True, exist_ok=True)
    end = time.time() + wait
    while True:
        try:
            os.mkdir(d); break
        except FileExistsError:
            try:
                if time.time() - d.stat().st_mtime > 30: os.rmdir(d); continue
            except OSError: pass
            if time.time() > end: raise SystemExit("continuity: lock busy")
            time.sleep(0.05)
    try: yield
    finally:
        with contextlib.suppress(OSError): os.rmdir(d)


def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "x"


def project_root(cwd):
    cwd = os.path.realpath(cwd or os.getcwd())
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip(): return os.path.realpath(r.stdout.strip())
    except Exception: pass
    return cwd


def pid_of(root): return f"{slug(os.path.basename(root))}-{hashlib.sha1(root.encode()).hexdigest()[:6]}"


def binding(pid): return jload(CONF / "projects" / f"{pid}.json")


def gconf(): return jload(CONF / "config.json", {}) or {}


def threshold(b):
    env = os.environ.get("CONTINUITY_THRESHOLD")
    for v in (env, (b or {}).get("threshold"), gconf().get("threshold"), DEFAULT_THRESHOLD):
        try:
            if v is not None and 1 <= float(v) <= 100: return float(v)
        except ValueError: pass
    return DEFAULT_THRESHOLD


def enabled(b):
    if os.environ.get("CONTINUITY_OFF") == "1": return False
    return gconf().get("enabled", True) and (b or {}).get("enabled", True)


def pdir(b):
    return Path(b["vault"]) / b["folder"] if b else None


def sess_file(sid): return STATE / "sessions" / f"{re.sub(r'[^A-Za-z0-9_-]', '', sid)}.json"


def trans_file(pid): return STATE / "projects" / pid / "transition.json"


def read_payload():
    try: return json.loads(sys.stdin.read() or "{}")
    except Exception: return {}


def out_ctx(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def session_title(tr):
    t = None
    try:
        with open(tr, errors="replace") as f:
            for l in f:
                if '"custom-title"' in l:
                    with contextlib.suppress(Exception): t = json.loads(l).get("customTitle") or t
    except OSError: pass
    return t


# ---------------------------------------------------------------- tap / hooks
def cmd_tap(a):
    p = read_payload(); sid = p.get("session_id")
    if not sid: return
    cw = p.get("context_window") or {}
    pct = cw.get("used_percentage")
    if pct is None and cw.get("remaining_percentage") is not None: pct = 100 - cw["remaining_percentage"]
    f = sess_file(sid); s = jload(f, {}) or {}
    root = project_root((p.get("workspace") or {}).get("project_dir") or p.get("cwd"))
    s.update(sid=sid, pct=pct, ts=time.time(), tr=p.get("transcript_path") or s.get("tr"),
             cwd=p.get("cwd"), root=root, pid=pid_of(root))
    s.setdefault("state", "none"); s.setdefault("events", 0)
    jsave(f, s)


def checkpoint_text(s, thr, b):
    pct = int(round(s.get("pct") or 0))
    title = session_title(s.get("tr") or "") or "<exact current session title>"
    bound = "" if b else ("Project has no Obsidian destination yet: follow SKILL.md 'First use' and ask once. ")
    return (f"[continuity] Context {pct}% >= {thr:g}%. {bound}Finish the current safe unit of work. "
            f"If only the final reply remains, finish here and write nothing. Otherwise: write a 150-300 word handoff "
            f"(latest user request, decisive evidence, untested items, running operations by id, ONE next action) and run "
            f"`python3 {SELF} handoff --title \"{title}\"` with the text on stdin; then run "
            f"`python3 {SELF} launch --sid {s['sid']}` and follow its output. Both commands are idempotent; do this once.")


def cmd_hook(a):
    p = read_payload(); ev = a.event; sid = p.get("session_id")
    if (STATE / "debug").exists(): jsave(STATE / f"payload-{ev}.json", {k: (v if k != "prompt" else "...") for k, v in p.items()})
    if not sid: return
    root = project_root(p.get("cwd")); pid = pid_of(root); b = binding(pid)
    if not enabled(b): return
    if ev == "SessionStart":
        return hook_start(p, sid, pid, b)
    if ev == "Stop":
        if b: archive(sid, p.get("transcript_path"), b, pid)
        return
    f = sess_file(sid); s = jload(f)
    if (not s or s.get("pct") is None) and gconf().get("window"):  # opt-in fallback when no status line signal
        s = s or {"sid": sid, "state": "none", "events": 0}; s["pct"] = estimate_pct(p.get("transcript_path"), float(gconf()["window"])); s["tr"] = p.get("transcript_path")
        if s["pct"] is None: return
    if not s or s.get("pct") is None: return
    thr = threshold(b); pct = float(s["pct"])
    if s.get("state") == "requested" and pct < thr - 15: s["state"] = "none"; s["events"] = 0
    if pct >= thr and s.get("state") == "none":
        s["state"] = "requested"; s["events"] = 0; jsave(f, s)
        return out_ctx(ev, checkpoint_text(s, thr, b))
    if s.get("state") == "requested":
        s["events"] = s.get("events", 0) + 1
        if s["events"] == 15: jsave(f, s); return out_ctx(ev, "[continuity] Checkpoint still pending: " + checkpoint_text(s, thr, b)[14:])
        jsave(f, s)


def hook_start(p, sid, pid, b):
    if p.get("source") in ("resume", "compact"): return
    tf = trans_file(pid)
    with lock(f"t-{pid}"):
        t = jload(tf)
        if not t or t.get("status") not in ("ready", "launched") or t.get("sid") == sid or time.time() - t.get("created", 0) > 3 * 86400:
            return out_ctx("SessionStart", "[continuity] active. " + ("Project bound; keep the state note current; user can say \"checkpoint\"." if b else "Project not bound: on first real work use the continuity skill to ask where notes go.") )
        text = re.sub(r"\A---.*?---\n", "", Path(t["handoff"]).read_text(), count=1, flags=re.S)[:3500] if Path(t["handoff"]).exists() else ""
        if not text: return out_ctx("SessionStart", "[continuity] active.")
        t.update(status="claimed", successor=sid, claimed=time.time()); jsave(tf, t)
    note = (pdir(b) / "current-state.md") if b else None
    out_ctx("SessionStart", f"[continuity] Continuing '{t.get('title')}'. Handoff {t['handoff']} (read, claimed). "
            f"State note: {note}. Do not re-launch anything listed as running; fetch more only if needed.\n\n{text}")


def estimate_pct(tr, window):
    try:
        with open(tr, "rb") as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - 400000)); lines = f.read().splitlines()
        for l in reversed(lines):
            if b'"usage"' in l:
                u = (json.loads(l).get("message") or {}).get("usage") or {}
                n = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                if n: return 100.0 * n / window
    except Exception: pass
    return None


# ---------------------------------------------------------------- archive
def keep_text(m):
    c = m.get("content")
    if isinstance(c, str): txt = c
    else: txt = "\n".join(x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text")
    txt = txt.strip()
    return "" if (not txt or txt.startswith("<system-reminder") or txt.startswith("<command-") or txt.startswith("Caveat:")) else txt


def archive(sid, tr, b, pid):
    if not tr or not os.path.exists(tr): return None
    offf = STATE / "sessions" / f"{sid}.archive.json"; o = jload(offf, {}) or {}
    pos = o.get("pos", 0); title = session_title(tr) or o.get("title") or "session"
    dest = pdir(b) / "transcripts" / f"{slug(title)}--{sid[:8]}.md"; dest.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    with open(tr, "rb") as f:
        f.seek(pos); data = f.read()
    end = data.rfind(b"\n") + 1
    for line in data[:end].splitlines():
        try: r = json.loads(line)
        except Exception: continue
        if r.get("isSidechain") or r.get("isMeta") or r.get("type") not in ("user", "assistant"): continue
        t = keep_text(r.get("message") or {})
        if t: chunks.append(f"\n### {'User' if r['type']=='user' else 'Assistant'} · {r.get('timestamp','')}\n{redact(t)}\n")
    if not dest.exists():
        dest.write_text(f"---\nsession_id: {sid}\nproject_id: {pid}\ntitle: {title}\n---\n# Transcript: {title}\n(User prompts and assistant replies only. Secrets redacted.)\n")
    if chunks:
        with open(dest, "a") as f: f.write("".join(chunks))
    jsave(offf, {"pos": pos + end, "title": title}); return dest


# ---------------------------------------------------------------- bind / status
def vaults():
    j = jload(HOME / "Library/Application Support/obsidian/obsidian.json", {}) or {}
    return [v["path"] for v in j.get("vaults", {}).values() if os.path.isdir(v.get("path", ""))]


def cmd_suggest(a):
    root = project_root(a.cwd); name = os.path.basename(root); toks = set(re.findall(r"[a-z0-9]+", name.lower()))
    scored = sorted(((len(toks & set(re.findall(r"[a-z0-9]+", os.path.basename(v).lower()))), v) for v in vaults()), reverse=True)
    print(json.dumps({"project_id": pid_of(root), "root": root, "suggested_folder": name,
                      "vaults": [{"path": v, "name_match": s} for s, v in scored]}, indent=1))


def cmd_bind(a):
    root = project_root(a.cwd); pid = pid_of(root)
    if not os.path.isdir(os.path.join(a.vault, ".obsidian")): sys.exit("not an Obsidian vault (no .obsidian): " + a.vault)
    b = binding(pid) or {}
    b.update(root=root, vault=os.path.realpath(a.vault), folder=a.folder.strip("/"), project=os.path.basename(root))
    if a.threshold: b["threshold"] = a.threshold
    jsave(CONF / "projects" / f"{pid}.json", b)
    d = pdir(b)
    for sub in ("handoffs", "transcripts"): (d / sub).mkdir(parents=True, exist_ok=True)
    print(f"bound {pid} -> {d}")


def cmd_status(a):
    root = project_root(a.cwd); pid = pid_of(root); b = binding(pid)
    print(json.dumps({"project_id": pid, "root": root, "bound": bool(b), "dir": str(pdir(b)) if b else None,
                      "threshold": threshold(b), "enabled": enabled(b), "transition": jload(trans_file(pid))}, indent=1))


def cmd_threshold(a):
    if a.scope == "global": g = gconf(); g["threshold"] = a.value; jsave(CONF / "config.json", g); print(f"global threshold {a.value}")
    else:
        pid = pid_of(project_root(a.cwd)); b = binding(pid)
        if not b: sys.exit("project not bound; use --global or bind first")
        b["threshold"] = a.value; jsave(CONF / "projects" / f"{pid}.json", b); print(f"{pid} threshold {a.value}")


def cmd_toggle(a):
    on = a.cmd == "enable"
    if a.scope == "global": g = gconf(); g["enabled"] = on; jsave(CONF / "config.json", g)
    else:
        pid = pid_of(project_root(a.cwd)); b = binding(pid) or sys.exit("project not bound")
        b["enabled"] = on; jsave(CONF / "projects" / f"{pid}.json", b)
    print(a.cmd + "d", a.scope)


def need_bound(a):
    root = project_root(a.cwd); pid = pid_of(root); b = binding(pid)
    if not b: sys.exit("project not bound: run `suggest`, ask the user once, then `bind`")
    return root, pid, b


# ---------------------------------------------------------------- note
def parse_note(t):
    secs = {k: "" for k in SECTIONS}; cur = None
    for l in t.splitlines():
        m = re.match(r"## (.+)", l)
        if m: cur = m.group(1).strip(); secs.setdefault(cur, ""); continue
        if cur: secs[cur] += l + "\n"
    return {k: v.strip() for k, v in secs.items()}


def render_note(pid, name, secs):
    body = "".join(f"\n## {k}\n{secs.get(k, '') or '-'}\n" for k in SECTIONS + [k for k in secs if k not in SECTIONS])
    return f"---\nproject_id: {pid}\nproject: {name}\nupdated: {time.strftime('%Y-%m-%d %H:%M')}\n---\n# {name}: current state\n{body}"


def cmd_note(a):
    root, pid, b = need_bound(a); f = pdir(b) / "current-state.md"
    secs = parse_note(f.read_text()) if f.exists() else {k: "" for k in SECTIONS}
    if a.action == "show": print(f.read_text() if f.exists() else "(no note yet)"); return
    if a.action == "set":
        text = redact((a.text if a.text is not None else sys.stdin.read()).strip())
        if a.section not in SECTIONS: sys.exit("section must be one of: " + ", ".join(SECTIONS))
        secs[a.section] = (secs[a.section] + "\n" + text).strip() if a.append and secs[a.section] not in ("", "-") else text
    f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_suffix(".tmp")
    tmp.write_text(render_note(pid, b["project"], secs)); os.replace(tmp, f); print("updated", f)


# ---------------------------------------------------------------- handoff / launch
def resolve_sid(a):
    """--sid optional: newest transcript for this cwd (Desktop has no status line signal)."""
    if getattr(a, "sid", None): return a.sid
    d = HOME / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(a.cwd))
    fs = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) if d.is_dir() else []
    if not fs: sys.exit("cannot detect session id; pass --sid")
    sf = sess_file(fs[0].stem); s = jload(sf, {}) or {}
    s.update(sid=fs[0].stem, tr=str(fs[0])); s.setdefault("state", "none"); s.setdefault("events", 0); jsave(sf, s)
    return fs[0].stem


def cmd_handoff(a):
    a.sid = resolve_sid(a)
    if not a.title: a.title = session_title((jload(sess_file(a.sid), {}) or {}).get("tr") or "") or sys.exit("no title found; pass --title")
    root, pid, b = need_bound(a); sf = sess_file(a.sid); s = jload(sf, {}) or {"sid": a.sid, "state": "none"}
    tf = trans_file(pid)
    with lock(f"t-{pid}"):
        t = jload(tf)
        if t and t.get("sid") == a.sid and Path(t["handoff"]).exists():
            print("EXISTS", t["handoff"]); return
        body = redact(sys.stdin.read().strip()); n = len(body.split())
        if n < 20 or n > MAX_HANDOFF_WORDS: sys.exit(f"handoff is {n} words; aim 150-300 (limits 20-{MAX_HANDOFF_WORDS})")
        title = a.title; arch = pdir(b) / "transcripts" / f"{slug(session_title(s.get('tr') or '') or title)}--{a.sid[:8]}.md"
        dest = pdir(b) / "handoffs" / f"{slug(title)}--{a.sid[:8]}.md"; dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"---\nproject_id: {pid}\nsession_id: {a.sid}\ntitle: {title}\ncreated: {time.strftime('%Y-%m-%d %H:%M')}\n---\n"
                        f"# Handoff: {title}\n\n{body}\n\nState note: [[{b['folder']}/current-state]]\nExact wording archive: [[{b['folder']}/transcripts/{arch.stem}]]\n")
        jsave(tf, {"status": "ready", "sid": a.sid, "title": title, "handoff": str(dest), "cwd": root, "created": time.time()})
        s["state"] = "written"; jsave(sf, s)
    print("WROTE", dest)


def cmd_launch(a):
    a.sid = resolve_sid(a)
    root, pid, b = need_bound(a); tf = trans_file(pid)
    with lock(f"t-{pid}"):
        t = jload(tf)
        if not t or t.get("sid") != a.sid: sys.exit("no handoff for this session: run `handoff` first")
        st = t["status"]
        if st == "claimed": print(f"ALREADY_CLAIMED by {t.get('successor')}: do nothing"); return
        if st == "launched" and time.time() - t.get("launched", 0) < STALE_LAUNCH_SEC and not a.force:
            print("ALREADY_LAUNCHED: do nothing (use --force only if the user says the successor never started)"); return
        t.update(status="launched", launched=time.time()); jsave(tf, t)
    prompt = f"Continue this project from the handoff at {t['handoff']}. It is also loaded at session start."
    q = lambda x: "'" + x.replace("'", "'\\''") + "'"
    print(json.dumps({
        "desktop_app": {"tool": "mcp__ccd_session__start_session", "initiation": "user_asked", "context": "fresh",
                        "title": t["title"], "cwd": t["cwd"], "prompt": prompt,
                        "background": f"Continuation of '{t['title']}'. Project {pid}. Handoff file {t['handoff']} holds the latest request, evidence and next action."},
        "cli_fallback": f"cd {q(t['cwd'])} && claude -n {q(t['title'])} {q(prompt)}",
        "note": "Original session is untouched. The successor's SessionStart hook marks the handoff claimed."}, indent=1))


def cmd_checkpoint(a):
    root = project_root(a.cwd); pid = pid_of(root); b = binding(pid)
    a.sid = resolve_sid(a)
    f = sess_file(a.sid); s = jload(f, {}) or {"sid": a.sid, "pct": 0}; s["state"] = "requested"; jsave(f, s)
    print(checkpoint_text(s, threshold(b), b))


# ---------------------------------------------------------------- find
def cmd_find(a):
    root, pid, b = need_bound(a); d = pdir(b); terms = [x.lower() for x in a.query.split()]; res = []
    for f in d.rglob("*.md"):
        if "transcripts" in f.parts and not a.transcripts: continue
        try: lines = f.read_text(errors="replace").splitlines()
        except OSError: continue
        low = "\n".join(lines).lower(); hit = sum(t in low for t in terms)
        if hit:
            ls = [(i + 1, l.strip()) for i, l in enumerate(lines) if any(t in l.lower() for t in terms)][:3]
            res.append((hit, f, ls))
    for hit, f, ls in sorted(res, key=lambda x: -x[0])[: a.n]:
        print(f"{f.relative_to(d)} ({hit}/{len(terms)} terms)")
        for i, l in ls: print(f"  {i}: {l[:160]}")
    if not res: print("no match")


def main():
    ap = argparse.ArgumentParser(prog="continuity"); sp = ap.add_subparsers(dest="cmd", required=True)
    def add(n, fn, **kw):
        p = sp.add_parser(n, **kw); p.add_argument("--cwd", default=os.getcwd()); p.set_defaults(fn=fn); return p
    add("tap", cmd_tap)
    add("hook", cmd_hook).add_argument("event")
    add("suggest", cmd_suggest)
    p = add("bind", cmd_bind); p.add_argument("--vault", required=True); p.add_argument("--folder", required=True); p.add_argument("--threshold", type=float)
    add("status", cmd_status)
    p = add("threshold", cmd_threshold); p.add_argument("value", type=float); p.add_argument("--scope", choices=["project", "global"], default="project")
    for n in ("enable", "disable"):
        add(n, cmd_toggle).add_argument("--scope", choices=["project", "global"], default="project")
    p = add("note", cmd_note); p.add_argument("action", choices=["show", "set"]); p.add_argument("--section"); p.add_argument("--text"); p.add_argument("--append", action="store_true")
    p = add("handoff", cmd_handoff); p.add_argument("--sid"); p.add_argument("--title")
    p = add("launch", cmd_launch); p.add_argument("--sid"); p.add_argument("--force", action="store_true")
    add("checkpoint", cmd_checkpoint).add_argument("--sid")
    p = add("find", cmd_find); p.add_argument("query"); p.add_argument("-n", type=int, default=6); p.add_argument("--transcripts", action="store_true")
    a = ap.parse_args()
    try: a.fn(a)
    except BrokenPipeError: pass
    except Exception as e:
        if a.cmd in ("tap", "hook"): return  # never break the host session
        raise


if __name__ == "__main__":
    main()
