#!/usr/bin/env python3
"""build_artifact.py의 build()가 만드는 조각을 완전한 HTML 문서로 감싸서
GitHub Pages가 그대로 서빙할 수 있는 index.html로 저장한다.
(Claude Artifact용 fragment와 달리 <html>/<head>/<body>를 직접 갖춘 완결 문서)
"""
import re
from pathlib import Path

from build_artifact import build

OUT_DIR = Path(__file__).parent

fragment = build()

m = re.match(
    r"\s*((?:<title>.*?</title>\s*|<link[^>]*>\s*|<style>.*?</style>\s*)+)(.*)",
    fragment, re.S,
)
head_bits, rest = (m.group(1), m.group(2)) if m else ("<title>커뮤니티 호외</title>", fragment)

doc = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head_bits}
</head>
<body>
{rest}
</body>
</html>
"""

out_path = OUT_DIR / "index.html"
out_path.write_text(doc, encoding="utf-8")
print(f"작성됨: {out_path} ({len(doc):,} bytes)")
