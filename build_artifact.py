#!/usr/bin/env python3
"""report_data.json을 읽어서 Claude Artifact로 게시할 수 있는 정적 HTML 조각을 만든다.
(scraper.py가 만드는 report.html과는 별개 — 이건 다른 사람들과 공유하는 공개용 디자인.)
"""
import json
import re
from pathlib import Path

OUT_DIR = Path(__file__).parent
DATA = json.loads((OUT_DIR / "report_data.json").read_text(encoding="utf-8"))
YSTR = DATA["date"]
RESULTS = DATA["results"]

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def fmt_date_ko(ystr: str) -> str:
    import datetime
    d = datetime.date.fromisoformat(ystr)
    return f"{d.year}년 {d.month}월 {d.day}일 ({WEEKDAY_KO[d.weekday()]})"


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


FLAG_KEYWORDS = ["ㅇㅎ", "ㅎㅂ", "약후", "후방"]


def is_flagged(title: str) -> bool:
    return any(kw in title for kw in FLAG_KEYWORDS)


def render_items(items, show_source=False):
    rows = []
    for p in items:
        meta_bits = []
        if p["views"]:
            meta_bits.append(f'<span class="stat"><i class="ic">조회</i>{p["views"]:,}</span>')
        if p["comments"]:
            meta_bits.append(f'<span class="stat"><i class="ic">댓글</i>{p["comments"]:,}</span>')
        if p["likes"]:
            meta_bits.append(f'<span class="stat"><i class="ic">추천</i>{p["likes"]:,}</span>')
        meta = "".join(meta_bits)
        src = f'<span class="src-tag">{p["_src_emoji"]} {esc(p["_src_name"])}</span>' if show_source else ""
        rows.append(
            f'<li><a class="post" href="{esc(p["url"])}">'
            f'{src}<span class="post-title">{esc(p["title"])}</span>'
            f'{f"<span class=post-meta>{meta}</span>" if meta else ""}'
            f'</a></li>'
        )
    return "\n".join(rows)


def build():
    total = sum(len(r["posts"]) for r in RESULTS if not r["error"])
    empty = [r for r in RESULTS if not r["error"] and not r["posts"]]
    errored = [r for r in RESULTS if r["error"]]

    # 각 커뮤니티에서 지정된 표현이 포함된 글은 빼서 맨 아래 한 섹션으로 모은다.
    flagged_all = []
    live = []
    for r in RESULTS:
        if r["error"] or not r["posts"]:
            continue
        normal, flagged = [], []
        for p in r["posts"]:
            (flagged if is_flagged(p["title"]) else normal).append(p)
        for p in flagged:
            flagged_all.append({**p, "_src_name": r["name"], "_src_emoji": r["emoji"]})
        if normal:
            live.append({**r, "posts": normal})

    nav_pills = "\n".join(
        f'<a class="pill" href="#sec-{i}"><span class="pill-emoji">{r["emoji"]}</span>{esc(r["name"])}'
        f'<span class="pill-count">{len(r["posts"])}</span></a>'
        for i, r in enumerate(live)
    )
    if flagged_all:
        nav_pills += (f'\n<a class="pill" href="#sec-flagged"><span class="pill-emoji">⚠️</span>주의 표현'
                      f'<span class="pill-count">{len(flagged_all)}</span></a>')

    sections = []
    for i, r in enumerate(live):
        posts = r["posts"]
        visible, rest = posts[:15], posts[15:]

        more_block = ""
        if rest:
            more_block = (
                f'<details class="more"><summary>+{len(rest)}건 더 보기</summary>'
                f'<ul class="post-list">{render_items(rest)}</ul></details>'
            )

        sections.append(f'''
        <details class="board" id="sec-{i}">
          <summary class="board-head">
            <span class="board-emoji">{r["emoji"]}</span>
            <span class="board-name">{esc(r["name"])}</span>
            <span class="board-count">{len(posts)}건</span>
          </summary>
          <ul class="post-list">{render_items(visible)}</ul>
          {more_block}
        </details>''')

    if flagged_all:
        visible, rest = flagged_all[:15], flagged_all[15:]
        more_block = ""
        if rest:
            more_block = (
                f'<details class="more"><summary>+{len(rest)}건 더 보기</summary>'
                f'<ul class="post-list">{render_items(rest, show_source=True)}</ul></details>'
            )
        sections.append(f'''
        <details class="board flagged-board" id="sec-flagged">
          <summary class="board-head">
            <span class="board-emoji">⚠️</span>
            <span class="board-name">주의 표현 포함 글</span>
            <span class="board-count">{len(flagged_all)}건</span>
          </summary>
          <ul class="post-list">{render_items(visible, show_source=True)}</ul>
          {more_block}
        </details>''')

    quiet_names = ", ".join(esc(r["name"]) for r in (empty + errored)) or "없음"

    return f'''<title>커뮤니티 호외</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=Noto+Sans+KR:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
  :root {{
    --paper: #f7f3ea;
    --ink: #211d16;
    --sub: #7a715d;
    --line: #e6ddc9;
    --card: #fffdf8;
    --accent: #cf4520;
    --accent-ink: #fffaf2;
    --badge-bg: #efe6d2;
    --badge-text: #55503f;
    --shadow: 0 1px 2px rgba(40, 30, 10, .05);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --paper: #17140e;
      --ink: #f1e9d8;
      --sub: #a89a7c;
      --line: #352f22;
      --card: #1f1b13;
      --accent: #ff7a4a;
      --accent-ink: #1a1006;
      --badge-bg: #2c2718;
      --badge-text: #cdbf9c;
      --shadow: 0 1px 3px rgba(0, 0, 0, .4);
    }}
  }}
  :root[data-theme="dark"] {{
    --paper: #17140e;
    --ink: #f1e9d8;
    --sub: #a89a7c;
    --line: #352f22;
    --card: #1f1b13;
    --accent: #ff7a4a;
    --accent-ink: #1a1006;
    --badge-bg: #2c2718;
    --badge-text: #cdbf9c;
    --shadow: 0 1px 3px rgba(0, 0, 0, .4);
  }}

  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: "Noto Sans KR", "Malgun Gothic", sans-serif;
    line-height: 1.55;
  }}
  a {{ color: inherit; }}

  .masthead {{
    border-bottom: 3px solid var(--ink);
    padding: 28px 20px 18px;
  }}
  .masthead-inner {{ max-width: 880px; margin: 0 auto; }}
  .kicker {{
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--accent);
    font-weight: 600;
  }}
  .masthead h1 {{
    font-family: "Gowun Batang", serif;
    font-size: clamp(32px, 6vw, 48px);
    font-weight: 700;
    margin: 6px 0 8px;
    text-wrap: balance;
  }}
  .masthead .date {{
    font-size: 14px;
    color: var(--sub);
  }}
  .stat-strip {{
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 18px;
  }}
  .stat-tile {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 3px;
    padding: 8px 14px;
    box-shadow: var(--shadow);
  }}
  .stat-tile b {{
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-variant-numeric: tabular-nums;
    font-size: 20px;
    color: var(--accent);
  }}
  .stat-tile span {{ font-size: 11px; color: var(--sub); }}

  .navbar {{
    position: sticky;
    top: 0;
    z-index: 5;
    background: var(--paper);
    border-bottom: 1px solid var(--line);
    padding: 10px 20px;
    overflow-x: auto;
  }}
  .navbar-inner {{
    max-width: 880px;
    margin: 0 auto;
    display: flex;
    gap: 8px;
  }}
  .pill {{
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 11px;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: var(--card);
    font-size: 12.5px;
    font-weight: 500;
    text-decoration: none;
    white-space: nowrap;
  }}
  .pill:hover {{ border-color: var(--accent); }}
  .pill-count {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10.5px;
    color: var(--sub);
  }}

  .wrap {{ max-width: 880px; margin: 0 auto; padding: 28px 20px 60px; }}

  .quiet-note {{
    font-size: 12px;
    color: var(--sub);
    border: 1px dashed var(--line);
    border-radius: 4px;
    padding: 10px 14px;
    margin-bottom: 28px;
  }}

  .board {{ margin-bottom: 12px; scroll-margin-top: 56px; }}
  .board[open] {{ margin-bottom: 34px; }}
  .board-head {{
    display: flex;
    align-items: baseline;
    gap: 9px;
    font-family: "Gowun Batang", serif;
    font-size: 21px;
    font-weight: 700;
    border-bottom: 2px solid var(--ink);
    padding-bottom: 7px;
    margin: 0 0 4px;
    cursor: pointer;
    list-style: none;
  }}
  .board-head::-webkit-details-marker {{ display: none; }}
  .board-head::before {{
    content: "▸";
    color: var(--accent);
    font-size: 15px;
    flex: none;
  }}
  .board[open] > .board-head::before {{ content: "▾"; }}
  .board:not([open]) {{ border-bottom: 1px solid var(--line); }}
  .board:not([open]) .board-head {{ border-bottom: none; padding-bottom: 10px; }}
  .board-emoji {{ font-size: 18px; }}
  .board-count {{
    margin-left: auto;
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    font-weight: 600;
    color: var(--accent-ink);
    background: var(--accent);
    padding: 2px 8px;
    border-radius: 3px;
  }}

  .post-list {{ list-style: none; margin: 0; padding: 0; }}
  .post-list li {{ border-bottom: 1px solid var(--line); }}
  .post-list li:last-child {{ border-bottom: none; }}
  .post {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 10px 2px;
    text-decoration: none;
  }}
  .post:hover .post-title {{ color: var(--accent); text-decoration: underline; }}
  .post-title {{
    flex: 1;
    min-width: 0;
    font-size: 14.5px;
    word-break: break-word;
  }}
  .src-tag {{
    flex: none;
    font-size: 11px;
    color: var(--badge-text);
    background: var(--badge-bg);
    border-radius: 3px;
    padding: 1px 6px;
    white-space: nowrap;
  }}
  .flagged-board .board-head {{ border-bottom-color: var(--accent); }}
  .post-meta {{
    flex: none;
    display: flex;
    gap: 10px;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    color: var(--sub);
    font-variant-numeric: tabular-nums;
  }}
  .stat .ic {{
    font-style: normal;
    font-size: 9.5px;
    color: var(--badge-text);
    background: var(--badge-bg);
    border-radius: 2px;
    padding: 1px 4px;
    margin-right: 3px;
  }}

  .more summary {{
    cursor: pointer;
    font-size: 12.5px;
    color: var(--sub);
    padding: 9px 2px;
    list-style: none;
  }}
  .more summary::-webkit-details-marker {{ display: none; }}
  .more summary::before {{ content: "▸ "; color: var(--accent); }}
  .more[open] summary::before {{ content: "▾ "; }}

  .footer {{
    max-width: 880px;
    margin: 40px auto 0;
    padding: 18px 20px 0;
    border-top: 1px solid var(--line);
    font-size: 11.5px;
    color: var(--sub);
    font-family: "JetBrains Mono", monospace;
  }}

  @media (max-width: 480px) {{
    .masthead {{ padding: 22px 16px 14px; }}
    .wrap {{ padding: 22px 16px 48px; }}
  }}
</style>

<header class="masthead">
  <div class="masthead-inner">
    <div class="kicker">DAILY DIGEST · 어제자 커뮤니티 베스트</div>
    <h1>커뮤니티 호외</h1>
    <div class="date">{fmt_date_ko(YSTR)} 기준 · 국내 커뮤니티 {len(live)}곳에서 가장 많이 본 글</div>
    <div class="stat-strip">
      <div class="stat-tile"><b>{total:,}</b><span>건 수집</span></div>
      <div class="stat-tile"><b>{len(live)}</b><span>개 커뮤니티</span></div>
      <div class="stat-tile"><b>{len(RESULTS)}</b><span>곳 시도</span></div>
    </div>
  </div>
</header>

<nav class="navbar"><div class="navbar-inner">{nav_pills}</div></nav>

<main class="wrap">
  <div class="quiet-note">오늘 조용했던 곳(글 없음 · 접속 실패): {quiet_names}</div>
  {"".join(sections)}
</main>

<div class="footer">community_best · {YSTR} 기준 수집 · 각 글은 원본 커뮤니티로 연결됨</div>

<script>
(function() {{
  var KEY = 'community-best-open-sections';
  function loadState() {{
    try {{ return JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch (e) {{ return {{}}; }}
  }}
  function saveState(state) {{
    try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}}
  }}
  function applyState() {{
    var state = loadState();
    document.querySelectorAll('details.board[id]').forEach(function(el) {{
      el.open = !!state[el.id];
    }});
  }}
  document.addEventListener('toggle', function(ev) {{
    var el = ev.target;
    if (el.tagName === 'DETAILS' && el.classList.contains('board') && el.id) {{
      var state = loadState();
      state[el.id] = el.open;
      saveState(state);
    }}
  }}, true);
  applyState();
  window.addEventListener('pageshow', applyState);
}})();
</script>
'''


if __name__ == "__main__":
    html = build()
    out = OUT_DIR / "artifact.html"
    out.write_text(html, encoding="utf-8")
    print(f"작성됨: {out}  ({len(html):,} bytes)")
