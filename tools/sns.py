"""Follower history for the ミス近大2026 finalists, and the public page that shows it.

The repository is the single home of the data: the Mac and GitHub Actions both add samples to
history.json, rebuild index.html and push. Run from the repository root.

  python3 -I tools/sns.py x                 fetch X counts (public fxtwitter API) into out/x.json
  python3 -I tools/sns.py record tt1=8908 ig2=5417 ...
                                            add out/x.json + the TikTok/Instagram counts read in the
                                            browser to history.json, then rebuild index.html
  python3 -I tools/sns.py push              commit and push to GitHub Pages
  python3 -I tools/sns.py auto-x            GitHub Actions: X only, skipped while the Mac is keeping up
  python3 -I tools/sns.py build             rebuild index.html from history.json
"""
import json, os, re, subprocess, sys, time, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "out")  # git-ignored scratch
HISTORY = os.path.join(REPO, "history.json")
TEMPLATE = os.path.join(REPO, "tools", "template.html")
INDEX = os.path.join(REPO, "index.html")
UA = {"User-Agent": "Mozilla/5.0 (compatible; hiyori-sns/1.1)"}
JST = 9 * 3600
# The Mac records everything at about :30. GitHub's run at about :50 only steps in when the newest X count is older than this.
MAC_FRESH_MS = 40 * 60e3

PEOPLE = [
    {"no": n, "name": name, "x": f"misskindai26_{n}", "ig": f"miss.kindai2026_no.{n}", "tt": f"misskindai2026_{n}"}
    for n, name in [(1, "田中美海"), (2, "白石ひより"), (3, "三好愛美"), (4, "鈴木凛々子"), (5, "仲子和里"),
                    (6, "山口小巻"), (7, "月城安菜"), (8, "高賀音羽"), (9, "松本七乃葉")]
]
PLATFORMS = ("x", "ig", "tt")


def git(*a):
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)


def now_ms():
    return int(time.time() * 1000)


def load_history():
    if os.path.exists(HISTORY):
        return json.load(open(HISTORY, encoding="utf-8"))
    return {"samples": []}


def save_history(hist):
    hist["samples"] = thin(hist["samples"], now_ms())
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)


def last_values(samples):
    last = {p: {} for p in PLATFORMS}
    for s in samples:
        for p in PLATFORMS:
            last[p].update(s.get(p) or {})
    return last


def thin(samples, now):
    keep, hours, days = [], {}, {}
    for s in samples:
        age = now - s["t"]
        if age <= 48 * 3600e3:
            keep.append(s)
        elif age <= 14 * 86400e3:
            hours.setdefault((s["t"] / 1000 + JST) // 3600, s)
        else:
            days[(s["t"] / 1000 + JST) // 86400] = s
    return sorted(list(days.values()) + list(hours.values()) + keep, key=lambda s: s["t"])


def sync(hist):
    """Fold in samples the other side (Mac or GitHub) pushed, and move our branch on top of theirs.

    Only history.json and index.html ever change remotely, and both are rebuilt from the merged
    samples, so a soft reset onto origin/main keeps every local file and loses no data."""
    if git("fetch", "-q", "origin", "main").returncode != 0:
        print("sync: fetch failed, using local history", file=sys.stderr)
        return hist
    r = git("show", "origin/main:history.json")
    if r.returncode == 0:
        have = {s["t"] for s in hist["samples"]}
        hist["samples"] += [s for s in json.loads(r.stdout).get("samples", []) if s["t"] not in have]
        hist["samples"].sort(key=lambda s: s["t"])
    git("reset", "-q", "--soft", "origin/main")
    return hist


def fetch_x():
    os.makedirs(OUT, exist_ok=True)
    got = {}
    for person in PEOPLE:
        try:
            req = urllib.request.Request("https://api.fxtwitter.com/" + person["x"], headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                user = json.load(r).get("user") or {}
            if isinstance(user.get("followers"), int):
                got[str(person["no"])] = user["followers"]
        except Exception as e:
            print(f"x{person['no']}: {e}", file=sys.stderr)
        time.sleep(0.5)
    with open(os.path.join(OUT, "x.json"), "w") as f:
        json.dump({"at": now_ms(), "x": got}, f)
    print("x:", got)
    return got


def plausible(new, old):
    # A real account doesn't lose half its followers between two runs; a misread page can.
    return old is None or new >= old * 0.5


def record(args):
    hist = sync(load_history())
    last = last_values(hist["samples"])
    now = now_ms()
    sample = {"t": now, "x": {}, "ig": {}, "tt": {}}
    xpath = os.path.join(OUT, "x.json")
    if os.path.exists(xpath):
        xj = json.load(open(xpath))
        if now - xj.get("at", 0) < 3600e3:
            sample["x"] = {k: v for k, v in xj["x"].items() if plausible(v, last["x"].get(k))}
    for a in args:
        m = re.fullmatch(r"(tt|ig)([1-9])=(\d+)", a.strip())
        if not m:
            print("skip:", a, file=sys.stderr)
            continue
        p, no, n = m.group(1), m.group(2), int(m.group(3))
        if plausible(n, last[p].get(no)):
            sample[p][no] = n
    if not any(sample[p] for p in PLATFORMS):
        print("nothing to record")
        return False
    hist["samples"].append(sample)
    save_history(hist)
    build(hist)
    print("recorded", {p: len(sample[p]) for p in PLATFORMS}, "samples:", len(hist["samples"]))
    return True


def build(hist):
    snap = {"builtAt": now_ms(), "people": PEOPLE, "samples": hist["samples"]}
    enc = json.dumps(snap, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = open(TEMPLATE, encoding="utf-8").read()
    page = re.sub(r'(<script type="application/json" id="snapshot">).*?(</script>)',
                  lambda m: m.group(1) + enc + m.group(2), page, count=1, flags=re.S)
    # The template is written for the Claude artifact viewer, which supplies the document shell; the public page carries its own.
    head, body = page.split('<div class="wrap">', 1)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(
            '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            '<meta name="robots" content="noindex">\n'
            '<meta property="og:title" content="ひよりSNSメーター">\n'
            '<meta property="og:description" content="ミス近大2026ファイナリスト9人のX・Instagram・TikTokフォロワー数（約1時間ごとに更新）">\n'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n'
            + head + '</head>\n<body>\n<div class="wrap">' + body + AUTO_RELOAD + '</body>\n</html>\n')


# An open copy checks for a newer build every 5 minutes and when the phone brings it back to the front.
# It jumps to a fresh ?v= address instead of reload(), because GitHub Pages lets browsers cache the page for 10 minutes.
AUTO_RELOAD = """<script>
(() => {
  const built = (() => { try { return JSON.parse(document.getElementById("snapshot").textContent).builtAt || 0; } catch (e) { return 0; } })();
  try { const y = sessionStorage.getItem("hiyori-sns-y"); if (y) { sessionStorage.removeItem("hiyori-sns-y"); addEventListener("load", () => scrollTo(0, +y)); } } catch (e) {}
  let busy = false;
  async function check() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const r = await fetch(location.pathname + "?v=" + Date.now(), { cache: "no-store" });
      const m = r.ok && (await r.text()).match(/"builtAt":(\\d+)/);
      if (m && +m[1] > built) {
        try { sessionStorage.setItem("hiyori-sns-y", String(scrollY)); } catch (e) {}
        location.replace(location.pathname + "?v=" + m[1]);
      }
    } catch (e) {}
    busy = false;
  }
  setInterval(check, 5 * 60e3);
  document.addEventListener("visibilitychange", check);
})();
</script>
"""


def push():
    for attempt in range(3):
        git("add", "-A")
        if git("diff", "--cached", "--quiet").returncode != 0:
            msg = ("Update follower counts " + time.strftime("%m/%d %H:%M", time.gmtime(time.time() + JST))
                   + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
            git("commit", "-q", "-m", msg)
        elif git("rev-list", "--count", "origin/main..HEAD").stdout.strip() in ("", "0"):
            print("push: no change")
            return True
        r = git("push", "-q", "origin", "HEAD:main")
        if r.returncode == 0:
            print("push: ok")
            return True
        print("push: rejected, merging the other side's samples:", r.stderr.strip()[-200:], file=sys.stderr)
        hist = sync(load_history())
        save_history(hist)
        build(hist)
    print("push: failed")
    return False


def auto_x():
    """GitHub Actions: keep X moving while the Mac sleeps. Never fails the workflow over a flaky read."""
    newest_x = max((s["t"] for s in load_history()["samples"] if s.get("x")), default=0)
    age = now_ms() - newest_x
    if age < MAC_FRESH_MS and not os.environ.get("FORCE"):
        print(f"skip: X was recorded {age / 6e4:.0f} min ago")
        return
    if fetch_x() and record([]):
        push()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "x":
        fetch_x()
    elif cmd == "record":
        sys.exit(0 if record(sys.argv[2:]) else 1)
    elif cmd == "build":
        build(load_history())
    elif cmd == "push":
        sys.exit(0 if push() else 1)
    elif cmd == "auto-x":
        auto_x()
    else:
        sys.exit(__doc__)
