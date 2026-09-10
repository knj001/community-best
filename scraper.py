#!/usr/bin/env python3
"""커뮤니티 베스트 어제 게시물 수집기"""
import sys
import re
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

KST       = timezone(timedelta(hours=9))
TODAY     = datetime.now(KST).date()
YESTERDAY = TODAY - timedelta(days=1)
YSTR      = YESTERDAY.strftime("%Y-%m-%d")
OUT_DIR   = Path(__file__).parent
REPORT    = OUT_DIR / "report.html"

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})
S.verify = False


# ── 공통 유틸 ─────────────────────────────────────────────────────────────────

def get(url, ref=None):
    try:
        h = {"Referer": ref} if ref else {}
        r = S.get(url, headers=h, timeout=20)
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    ✘ {e}")
        return None


def n(s) -> int:
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else 0


def parse_date(s: str):
    """가능하면 절대 날짜(date)로 변환. 시간만 있거나 파싱 불가면 None.
    ("오늘"인지 "어제"인지는 알지만 정확한 날짜를 알 수 없는 HH:MM류 표기는 None으로 취급)
    """
    s = s.strip()
    if not s:
        return None
    if s == "어제":
        return YESTERDAY
    if s == "오늘":
        return TODAY
    m = re.match(r"^(\d+)\s*(일|시간|분|초)\s*전$", s)
    if m:
        num, unit = int(m.group(1)), m.group(2)
        now = datetime.now(KST)
        delta = {"일": timedelta(days=num), "시간": timedelta(hours=num),
                 "분": timedelta(minutes=num), "초": timedelta(seconds=num)}[unit]
        return (now - delta).date()
    # YYYY-MM-DD (앞 10자만 사용, 뒤에 시간 붙어도 OK)
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except Exception:
            pass
    # YY/MM/DD (디시인사이드 등)
    for fmt in ("%y/%m/%d", "%y.%m.%d", "%y-%m-%d"):
        try:
            return datetime.strptime(s[:8], fmt).date()
        except Exception:
            pass
    # MM.DD / MM-DD / MM/DD (연도 없이)
    for fmt in ("%m.%d", "%m-%d", "%m/%d"):
        try:
            return datetime.strptime(s[:5], fmt).date().replace(year=TODAY.year)
        except Exception:
            pass
    return None


def is_yday(s: str) -> bool:
    return parse_date(s) == YESTERDAY


class DayRollback:
    """HH:MM(:SS)만 찍히는 목록(인벤/에스엘알클럽 등)에서 자정을 넘은 지점을 감지해
    실제 날짜를 복원한다. "인기글" 류 게시판은 등록순이 아니라 인기 점수 순이라
    몇 분 단위로 순서가 살짝 흔들리는데, 그걸 자정 통과로 오인하면 안 되므로
    THRESHOLD(기본 2시간)보다 크게 시각이 튀어오를 때만 진짜 자정 통과로 본다.
    """
    THRESHOLD = 2 * 3600

    def __init__(self, start_date=None):
        self.date = start_date if start_date is not None else TODAY
        self.min_seen = None

    def date_for(self, seconds: int):
        if self.min_seen is None or seconds <= self.min_seen + self.THRESHOLD:
            self.min_seen = seconds if self.min_seen is None else min(self.min_seen, seconds)
        else:
            self.date -= timedelta(days=1)
            self.min_seen = seconds
        return self.date


FLAG_KEYWORDS = ["ㅇㅎ", "ㅎㅂ", "약후", "후방"]


def is_flagged(title: str) -> bool:
    return any(kw in title for kw in FLAG_KEYWORDS)


def mk(title, url, date_s, views=0, comments=0, likes=0):
    return {
        "title": title.strip(),
        "url": url,
        "date": date_s,
        "views": views,
        "comments": comments,
        "likes": likes,
    }


# ── 스크래퍼 ─────────────────────────────────────────────────────────────────

def scrape_arca():
    """아카라이브 arca.live/b/live ("베스트 라이브" — 전체 채널 통합 추천글).
    처음 썼던 /b/breaking은 실시간으로 계속 굴러가는 라이브 피드라 페이지를 아무리 넘겨도
    거의 항상 당일 글만 나옴. /b/live는 추천순 정렬이라 하루~이틀치 글이 섞여서 나오고,
    개별 카드 구조도 달라서(div.vrow.hybrid, a.vrow 아님) 선택자를 새로 잡아야 했음.
    datetime 속성이 UTC(Z)라서 그냥 앞 10글자만 자르면 자정 근처에서 하루 밀릴 수 있어
    KST로 변환한 뒤 날짜를 비교한다. 추천순이라 페이지별 날짜가 뒤섞여 있어 "지나치면 멈춤"
    방식 대신 앞쪽 몇 페이지를 고정으로 훑는다.
    """
    posts = []
    for page in (1, 2, 3, 4):
        url = "https://arca.live/b/live" if page == 1 else f"https://arca.live/b/live?p={page}"
        soup = get(url, ref="https://arca.live/")
        if not soup:
            continue
        for row in soup.select("div.vrow.hybrid"):
            title_el = row.select_one("a.title.hybrid-title")
            time_el  = row.select_one(".col-time time[datetime]")
            if not title_el or not time_el or not time_el.get("datetime"):
                continue
            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True))
            title = re.sub(r"\s*\[\d+\]$", "", title).strip()
            href  = title_el.get("href", "")
            url_a = ("https://arca.live" + href) if href.startswith("/") else href
            utc_dt   = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
            date_str = utc_dt.astimezone(KST).strftime("%Y-%m-%d")
            if not is_yday(date_str):
                continue
            view_el = row.select_one(".col-view")
            cmnt_el = row.select_one(".comment-count")
            posts.append(mk(title, url_a, date_str,
                            views=n(view_el.text if view_el else 0),
                            comments=n(cmnt_el.text if cmnt_el else 0)))
    return posts


def scrape_slr():
    """에스엘알클럽 slrclub.com — 인기글(id=hot_article, 전체 게시판 통합 인기글).
    404로 알려져 있었지만 실제로는 살아있음(구 URL 경로만 잘못돼 있었음).
    처음엔 자유게시판(id=free)을 썼는데 트래픽이 너무 많아 하루치가 800건대로 나와서
    (사용자 요청으로) 전체 게시판 인기글만 모아주는 hot_article 게시판으로 교체함.
    이 게시판의 page= 파라미터는 "1페이지, 2페이지..."가 아니라 진짜 순차 페이지 번호라
    20여년치 역사 탓에 숫자가 몇만대다. 페이지네이션 위젯에 걸린 숫자 중 최댓값+1이 현재
    페이지. 날짜는 오늘 글이면 "HH:MM:SS"만 나오고 그 이전이어도 마찬가지라(인벤과 동일 문제).
    다만 "인기글"은 등록순이 아니라 인기 점수순이라 몇 분 단위로 순서가 흔들리므로,
    DayRollback으로 크게(2시간 이상) 시각이 튀어오를 때만 자정 통과로 판단한다.
    """
    board_url = "https://www.slrclub.com/bbs/zboard.php?id=hot_article&category=&setsearch=category"
    soup = get(board_url, ref="https://www.slrclub.com/")
    if not soup:
        return []
    page_nums = set()
    for a in soup.select("a[href*='page=']"):
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            page_nums.add(int(m.group(1)))
    cur_page = (max(page_nums) + 1) if page_nums else None

    posts = []
    rollback = DayRollback()
    pages_to_fetch = [None] if cur_page is None else list(range(cur_page, max(cur_page - 60, 0), -1))
    for pageno in pages_to_fetch:
        if pageno is None:
            page_soup = soup
        else:
            url = f"{board_url}&page={pageno}"
            page_soup = get(url, ref="https://www.slrclub.com/")
        if not page_soup:
            break
        rows = page_soup.select("tr")
        if not rows:
            break
        passed_yday = False
        for row in rows:
            a = row.select_one("td.sbj a")
            date_el = row.select_one("td.list_date")
            if not a or not date_el:
                continue
            title    = a.get_text(strip=True)
            href     = a.get("href", "")
            url_a    = ("https://www.slrclub.com" + href) if href.startswith("/") else href
            date_str = date_el.get_text(strip=True)
            hms = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", date_str)
            if hms:
                seconds = int(hms.group(1)) * 3600 + int(hms.group(2)) * 60 + int(hms.group(3))
                d = rollback.date_for(seconds)
            else:
                d = parse_date(date_str)
            if d is not None and d < YESTERDAY and (TODAY - d).days <= 3:
                passed_yday = True
                continue
            if d != YESTERDAY:
                continue
            view_el = row.select_one("td.list_click")
            posts.append(mk(title, url_a, date_str,
                            views=n(view_el.text if view_el else 0)))
        if passed_yday or pageno is None:
            break
    return posts


def scrape_ppomppu():
    """뽐뿌 ppomppu.co.kr — 유머게시판(id=humor)
    "차단/리다이렉트됨"이라 적혀 있었는데 실제로 다시 확인해보니 정상 접근됨.
    날짜는 time.baseList-time의 title 속성에 "YY.MM.DD HH:MM:SS"로 절대시각이 들어있어
    파싱이 쉽고, 페이지도 보통의 1,2,3... 순서라 어제 날짜 나올 때까지만 넘기면 된다.
    """
    posts = []
    for page in range(1, 8):
        url = f"https://www.ppomppu.co.kr/zboard/zboard.php?id=humor&page={page}"
        soup = get(url, ref="https://www.ppomppu.co.kr/")
        if not soup:
            break
        rows = soup.select("tr.baseList")
        if not rows:
            break
        passed_yday = False
        for row in rows:
            a = row.select_one("a.baseList-title")
            time_el = row.select_one("time.baseList-time")
            if not a or not time_el:
                continue
            title    = a.get_text(strip=True)
            href     = a.get("href", "")
            url_a    = ("https://www.ppomppu.co.kr/zboard/" + href) if not href.startswith("http") else href
            date_str = time_el.get("title", "")[:8]
            d = parse_date(date_str)
            if d is not None and d < YESTERDAY and (TODAY - d).days <= 3:
                passed_yday = True
                continue
            if d != YESTERDAY:
                continue
            view_el = row.select_one("td.baseList-views")
            posts.append(mk(title, url_a, date_str,
                            views=n(view_el.text if view_el else 0)))
        if passed_yday:
            break
    return posts


def scrape_dogdrip():
    """개드립 dogdrip.net — 인기글
    XE 기반. 목록 항목은 <li class="... webzine">, 날짜는 절대날짜가 아니라
    ".list-meta" 안에 "N 시간 전 / N 분 전 / N 일 전" 형태의 상대시간으로만 나온다.
    인기순 정렬이라 "어제" 글이 나오려면 페이지를 꽤 넘겨야 한다(실측상 6~9페이지대).
    그래서 어제보다 더 오래된 글이 나올 때까지 계속 넘기다가 지나치면 멈춘다.
    """
    posts = []
    for page in range(1, 16):
        soup = get(f"http://www.dogdrip.net/dogdrip?sort_index=popular&page={page}",
                   ref="http://www.dogdrip.net/")
        if not soup:
            continue
        rows = soup.select("li.webzine")
        if not rows:
            break
        passed_yday = False
        for li in rows:
            a = li.select_one("a.title-link")
            if not a or len(a.get_text(strip=True)) < 2:
                continue
            title = a.get_text(strip=True)
            href  = a.get("href", "")
            url   = urljoin("http://www.dogdrip.net/dogdrip", href)
            meta  = li.select_one(".list-meta")
            m = re.search(r"(\d+)\s*(일|시간|분)\s*전", meta.get_text(" ", strip=True)) if meta else None
            date_str = f"{m.group(1)}{m.group(2)} 전" if m else ""
            d = parse_date(date_str)
            if d is not None and d < YESTERDAY:
                passed_yday = True
                continue
            if d != YESTERDAY:
                continue
            posts.append(mk(title, url, date_str))
        if passed_yday:
            break
    return posts


ETOLAND_ITEM_RE = re.compile(
    r'\\"wrId\\":(?P<wr>\d+),\\"category\\":\\"(?P<cat>.*?)\\",\\"device\\":\\"(?:pc|mobile)\\".*?'
    r'\\"subject\\":\\"(?P<subj>.*?)\\".*?'
    r'\\"commentCount\\":(?P<cmt>\d+).*?'
    r'\\"writeDateTimestamp\\":(?P<ts>\d+).*?'
    r'\\"recommendCount\\":(?P<rec>\d+).*?'
    r'\\"viewCount\\":(?P<view>\d+).*?'
    r'\\"slug\\":\\"(?P<slug>.*?)\\"'
)


def scrape_etoland():
    """이토랜드 — 2026년경 Next.js(App Router, RSC) 기반으로 전면 개편됨.
    화면엔 클라이언트 하이드레이션으로 채워지지만, 서버가 내려주는 원본 HTML 안에
    `self.__next_f.push(...)` RSC 페이로드 문자열 안에 게시글 목록 JSON이 그대로 이스케이프되어
    박혀 있음(=BeautifulSoup으로 DOM을 뒤질 필요 없이 정규식으로 JSON 필드를 바로 뽑아낼 수 있음).
    단, bo_table=etohumor02는 2020년대 글만 있는 "예전게시판"(archived) 이라 반드시
    현재 활성 유머게시판인 etohumor07(/b/etohumor07/list)을 써야 함.
    정렬 버튼(추천순/조회순)은 클라이언트 전용 API라 쿼리파라미터로 흉내낼 수 없어서,
    기본(최신순) 목록을 페이지째 넘기며 어제 날짜 글만 모은다(다른 사이트와 동일한
    "어제보다 오래된 글이 나오면 멈춤" 패턴). 상단에 고정되는 오래된 공지글은
    (TODAY - d).days <= 3 범위를 벗어나면 무시해서 조기 종료를 막는다.
    """
    posts = []
    for page in range(1, 40):
        soup_src = get(f"https://www.etoland.co.kr/b/etohumor07/list?page={page}",
                        ref="https://www.etoland.co.kr/b/etohumor07/list")
        if soup_src is None:
            break
        html = str(soup_src)
        idx = html.find('\\"board\\":{\\"boTable\\":\\"etohumor07\\"')
        idx2 = html.find('\\"articleList\\":[', idx) if idx != -1 else -1
        if idx2 == -1:
            break
        window = html[idx2: idx2 + 80000]
        matches = list(ETOLAND_ITEM_RE.finditer(window))
        if not matches:
            break
        passed_yday = False
        for m in matches:
            ts = int(m.group("ts")) / 1000
            d = datetime.fromtimestamp(ts, KST).date()
            if d == YESTERDAY:
                title = m.group("subj")
                url_a = urljoin("https://www.etoland.co.kr/b/etohumor07/list",
                                 f"/b/etohumor07/view/{m.group('slug')}")
                posts.append(mk(title, url_a, YSTR,
                                 views=n(m.group("view")), comments=n(m.group("cmt")),
                                 likes=n(m.group("rec"))))
            elif d < YESTERDAY and (TODAY - d).days <= 3:
                passed_yday = True
        if passed_yday:
            break
    return posts


def scrape_todayhumor():
    """오늘의유머 todayhumor.co.kr — bestofbest"""
    soup = get("http://www.todayhumor.co.kr/board/list.php?table=bestofbest",
               ref="http://www.todayhumor.co.kr/")
    if not soup:
        return []
    posts = []
    seen = set()
    for a in soup.select("a[href*='view.php']"):
        title = a.get_text(strip=True)
        # 숫자만인 링크(글번호) 제외
        if not title or title.isdigit():
            continue
        if title in seen:
            continue
        seen.add(title)
        href  = a.get("href", "")
        url   = urljoin("http://www.todayhumor.co.kr/board/list.php", href)
        row   = a.find_parent("tr")
        if not row:
            continue
        tds   = row.select("td")
        # td[4] = 날짜 (26/09/07 16:08 형식)
        date_str = tds[4].get_text(strip=True) if len(tds) > 4 else ""
        if not is_yday(date_str):
            continue
        views    = n(tds[5].text) if len(tds) > 5 else 0
        comments = n(tds[6].text) if len(tds) > 6 else 0
        posts.append(mk(title, url, date_str, views=views, comments=comments))
    return posts


def scrape_ruliweb():
    """루리웹 ruliweb.com — 유머 베스트
    "베스트"(/best/board/...) 단일 글 URL은 실시간 라이브 피드라 못 쓰지만, 목록 페이지
    `/best/humor`(유머 BEST 랭킹)가 따로 있음. 이 목록은 날짜를 "16:47"(오늘=시각만) 또는
    "26.09.08"(오늘이 아니면 절대 YY.MM.DD) 두 형태로 섞어서 보여줘서 DayRollback 없이도
    parse_date만으로 정확히 "어제 글"을 골라낼 수 있음.
    다만 이 유머게시판은 하루 게시량 자체가 매우 많아서(초당 여러 건) 등록순/베스트선정순
    어느 정렬로 끝까지 페이지를 넘겨도 어제자 전체를 다 모으려면 페이지가 사실상 끝없이
    이어짐(직접 테스트 결과 30페이지를 넘겨도 안 끝남). 그래서 recommend(추천수) 정렬 +
    range=24h(최근 24시간, 오늘/어제 글이 섞여서 나옴)로 조회한 뒤, 그중 실제 날짜가
    어제인 것만 골라 적당한 페이지 수(12페이지)만큼만 모은다 — 인벤/82쿡과 같은 방식으로
    "그 시점 기준 상위 추천글" 스냅샷을 쓰는 근사치.
    """
    posts = []
    for page in range(1, 13):
        url = f"https://bbs.ruliweb.com/best/humor?orderby=recommend&range=24h&page={page}"
        soup = get(url, ref="https://bbs.ruliweb.com/best/humor")
        if not soup:
            break
        rows = soup.select("tr.table_body")
        if not rows:
            break
        for row in rows:
            a = row.select_one("td.subject a")
            if not a:
                continue
            date_el  = row.select_one("td.time")
            date_str = date_el.get_text(strip=True) if date_el else ""
            if not is_yday(date_str):
                continue
            title_el = a.select_one(".text_over") or a
            title = title_el.get_text(strip=True)
            href  = a.get("href", "").split("?")[0]
            url_a = urljoin("https://bbs.ruliweb.com/", href)
            view_el = row.select_one("td.hit")
            cmnt_el = row.select_one("span.num_reply, td.recomd")
            posts.append(mk(title, url_a, date_str,
                            views=n(view_el.text if view_el else 0),
                            comments=n(cmnt_el.text if cmnt_el else 0)))
    return posts


def scrape_ygosu():
    """와이고수 ygosu.com — 엽게
    1페이지는 당일(HH:MM) 글만 있고, 어제 글(YY.MM.DD 표기)은 2페이지부터 나온다.
    """
    posts = []
    for page in (1, 2):
        url = f"http://ygosu.com/board/real_article/yeobgi/?type=group0&page={page}"
        soup = get(url, ref="http://ygosu.com/")
        if not soup:
            continue
        for row in soup.select("table tr"):
            a = row.select_one("td.tit a")
            if not a:
                continue
            title    = a.get_text(strip=True)
            href     = a.get("href", "")
            url_a    = href if href.startswith("http") else "http://ygosu.com" + href
            date_el  = row.select_one("td.date")
            date_str = date_el.get_text(strip=True) if date_el else ""
            if not is_yday(date_str):
                continue
            view_el = row.select_one("td.read")
            posts.append(mk(title, url_a, date_str,
                            views=n(view_el.text if view_el else 0)))
    return posts


def scrape_theqoo():
    """더쿠 theqoo.net — HOT
    페이지 맨 위 5개는 페이지 번호와 무관하게 항상 똑같이 반복되는 고정 공지인데(tr.notice),
    날짜 형식도 제각각(예: "09.06"처럼 3일 이내로 보이는 것도 있어서) 이걸 실제 목록과 섞어
    "어제보다 오래된 글 발견 → 그만 페이징" 판정에 넣으면 공지 때문에 1페이지만 보고 조기
    종료해버림(실제로 처음 구현에서 이 버그로 0건이 나왔음). 그래서 tr.notice류는 아예
    순회에서 제외한다. 실제 목록은 시각(HH:MM, 오늘) 또는 MM.DD(오늘이 아니면) 순서로 계속
    과거로 내려가는 진짜 페이지네이션이라 여러 페이지를 넘기면 어제 글에 도달한다
    (실측 3~6페이지가 어제, 7페이지부터 그제).
    """
    posts = []
    for page in range(1, 10):
        soup = get(f"https://theqoo.net/hot?page={page}", ref="https://theqoo.net/")
        if not soup:
            break
        rows = [r for r in soup.select("table.theqoo_board_table tr, table.bd_lst tr")
                if not any(c.startswith("notice") for c in (r.get("class") or []))]
        if not rows:
            break
        passed_yday = False
        for row in rows:
            a = row.select_one("td.title a")
            if not a:
                continue
            date_el  = row.select_one("td.time")
            date_str = date_el.get_text(strip=True) if date_el else ""
            d = parse_date(date_str)
            if d is not None and d < YESTERDAY and (TODAY - d).days <= 3:
                passed_yday = True
                continue
            if d != YESTERDAY:
                continue
            title = a.get_text(strip=True)
            href  = a.get("href", "").split("?")[0]
            url   = urljoin("https://theqoo.net/hot", href)
            view_el = row.select_one("td.m_no")
            posts.append(mk(title, url, date_str,
                            views=n(view_el.text if view_el else 0)))
        if passed_yday:
            break
    return posts


def scrape_instiz():
    """인스티즈 instiz.net — 포텐(인기) 게시판 `/pt`
    예전엔 Cloudflare "Just a moment..." JS 챌린지로 막혀 있었는데, 지금은 재확인해보니
    챌린지 없이 바로 200으로 정상 응답됨(사이트 쪽에서 정책이 바뀐 듯).
    URL은 사용자 요청으로 `?&category=2&srt=3&srd=2`(유머·감동 카테고리, HOT 정렬)를 사용.
    (실측으로는 이 파라미터를 붙여도 정적 요청 결과 자체는 기본 /pt와 동일한 스냅샷이지만,
    사용자가 명시적으로 지정한 URL이므로 그대로 유지)
    목록은 `tr[id=detour]` 행이고, 첫 `td.listno`가 날짜: 오늘이면 "12:37"/"5:45"처럼
    시각만, 오늘이 아니면 "09.08 23:43"처럼 MM.DD가 붙어 나옴(parse_date의 "%m.%d" 처리가
    앞 5글자만 봐서 그대로 먹힘). "더보기"는 JS AJAX(getnextpage)라 정적 요청으론 더 못
    넘기고, 최초 로드에 이미 들어있는 스냅샷(15개 안팎)만 수집 가능 — 82쿡 위젯과 비슷하게
    깊은 과거까지는 못 가지만 어제자로 확실히 찍힌 것만 골라 담는다.
    """
    soup = get("https://www.instiz.net/pt?&category=2&srt=3&srd=2", ref="https://www.instiz.net/pt")
    if not soup:
        return []
    posts = []
    for row in soup.select("tr[id=detour]"):
        a = row.select_one("td.listsubject a")
        if not a:
            continue
        date_tds = row.select("td.listno")
        date_str = date_tds[0].get_text(strip=True) if date_tds else ""
        if not is_yday(date_str):
            continue
        title_el = a.select_one("span.texthead_notice") or a
        cmt_el = title_el.select_one("span.cmt3")
        cmt_text = cmt_el.get_text(strip=True) if cmt_el else ""
        title = title_el.get_text(strip=True)
        if cmt_text and title.endswith(cmt_text):
            title = title[:-len(cmt_text)].strip()
        href = a.get("href", "")
        url_a = urljoin("https://www.instiz.net/pt", href)
        views = n(date_tds[1].text) if len(date_tds) > 1 else 0
        comments = n(date_tds[2].text) if len(date_tds) > 2 else 0
        likes = n(cmt_text) if cmt_text else 0
        posts.append(mk(title, url_a, date_str, views=views, comments=comments, likes=likes))
    return posts


def scrape_ddanzi():
    """딴지일보 ddanzi.com — 베스트"""
    soup = get("http://www.ddanzi.com/index.php?mid=free&statusList=BEST,HOTBEST,BESTAC,HOTBESTAC",
               ref="http://www.ddanzi.com/")
    if not soup:
        return []
    posts = []
    for row in soup.select("table tr"):
        a = row.select_one("td.title a")
        if not a:
            continue
        title    = a.get_text(strip=True)
        href     = a.get("href", "")
        url      = href if href.startswith("http") else "http://www.ddanzi.com" + href
        date_el  = row.select_one("td.time")
        date_str = date_el.get_text(strip=True) if date_el else ""
        if not is_yday(date_str):
            continue
        view_el = row.select_one("td.hit")
        posts.append(mk(title, url, date_str,
                        views=n(view_el.text if view_el else 0)))
    return posts


def scrape_cook82():
    """82쿡 82cook.com — 자유게시판(bn=15) 사이드바의 "최근 많이 읽은 글" 위젯.
    자유게시판 목록 자체는 트래픽이 너무 많아 하루치를 거르기 번거롭고, 사용자가
    직접 지정한 이 위젯(div.leftbox.Best)을 그대로 가져온다. 위젯 항목엔 날짜가
    없어(최근 며칠간 조회수 상위 글 모음) is_yday로 거르지 않고 있는 그대로 수집.
    """
    soup = get("https://www.82cook.com/entiz/enti.php?bn=15",
               ref="https://www.82cook.com/")
    if not soup:
        return []
    posts = []
    box = soup.select_one("div.leftbox.Best ul.most")
    if not box:
        return []
    for a in box.select("li a"):
        title = a.get_text(strip=True)
        href  = a.get("href", "")
        url_a = urljoin("https://www.82cook.com/entiz/enti.php", href)
        posts.append(mk(title, url_a, ""))
    return posts


def scrape_dcinside():
    """디시인사이드 — 실시간 베스트
    page= 파라미터로 페이지네이션이 되는 진짜 목록이라 여러 페이지 넘기면 어제 글에 닿는다
    (실측 3페이지쯤부터 어제자). 예전엔 1페이지만 봐서 늘 0건이었음.
    주의: 목록 맨 위에 실제 글이 아닌 설문조사(투표) 위젯이 tr.ub-content 형태로 끼어
    있는데, 이 행만 td.gall_date에 title(ISO datetime) 속성이 비어 있고 "26/09/07" 같은
    이상한 텍스트만 있음 — 그대로 쓰면 날짜가 애매하게 "2~3일 전"으로 잡혀서 여러 페이지에
    걸쳐 반복 등장할 때마다 "어제보다 오래된 글 발견"으로 오판, 조기 종료를 일으킴. 그래서
    title 속성이 없는 행(=진짜 게시글이 아닌 위젯/공지)은 아예 건너뛴다.
    """
    posts = []
    for page in range(1, 12):
        soup = get(f"https://gall.dcinside.com/board/lists/?id=dcbest&page={page}",
                   ref="https://www.dcinside.com/")
        if not soup:
            break
        rows = soup.select("tr.ub-content")
        if not rows:
            break
        passed_yday = False
        for row in rows:
            a = row.select_one("td.gall_tit a:not(.reply_num):not(.written_sno)")
            if not a:
                continue
            date_el = row.select_one("td.gall_date")
            iso = date_el.get("title", "") if date_el else ""
            if not iso:
                continue
            date_str = iso[:10]
            d = parse_date(date_str)
            if d is not None and d < YESTERDAY and (TODAY - d).days <= 3:
                passed_yday = True
                continue
            if d != YESTERDAY:
                continue
            title = a.get_text(strip=True)
            href  = a.get("href", "")
            url   = urljoin("https://gall.dcinside.com/board/lists/", href)
            view_el = row.select_one("td.gall_count")
            cmnt_el = row.select_one("td.gall_comment")
            posts.append(mk(title, url, date_str,
                            views=n(view_el.text if view_el else 0),
                            comments=n(cmnt_el.text if cmnt_el else 0)))
        if passed_yday:
            break
    return posts


def scrape_fmkorea():
    """에펨코리아 fmkorea.com — FM베스트
    날짜는 li 안 span.regdate 에 "N 시간 전"/"N 분 전"/"N 일 전"으로 들어있는데,
    이게 한 단어(token)가 아니라 "N", "시간", "전"으로 공백 분리되어 있어서
    기존의 단어 단위 토큰 검색으로는 절대 못 잡았음 -> selector로 직접 추출.
    ?page=2 를 붙이면 봇 차단 페이지(HTTP 430)가 뜨므로 1페이지만 수집한다
    (자정을 넘나드는 "N시간 전"은 is_yday가 실제 시각을 계산해 어제 여부를 판단).
    """
    posts = []
    for page in (1,):
        url = "https://www.fmkorea.com/best" if page == 1 else f"https://www.fmkorea.com/best?page={page}"
        soup = get(url, ref="https://www.fmkorea.com/")
        if not soup:
            continue
        for li in soup.select("li.li"):
            links = li.select("a")
            title_a = next((a for a in links if "pc_voted_count" not in " ".join(a.get("class", []))), None)
            if not title_a:
                continue
            title = title_a.get_text(strip=True)
            if not title or title.isdigit():
                continue
            href  = title_a.get("href", "")
            url_a = ("https://www.fmkorea.com" + href) if href.startswith("/") else href
            date_el  = li.select_one(".regdate")
            date_str = re.sub(r"\s+", "", date_el.get_text(strip=True)) if date_el else ""
            # "N일전" -> is_yday가 기대하는 "N일 전" 형태로 정규화
            date_str = re.sub(r"(\d+)일전$", r"\1일 전", date_str)
            if not is_yday(date_str):
                continue
            posts.append(mk(title, url_a, date_str))
    return posts


def scrape_humoruniv():
    """웃긴대학 humoruniv.com — 오늘의유머"""
    soup = get("http://web.humoruniv.com/board/humor/list.html?table=pds&st=day",
               ref="http://web.humoruniv.com/")
    if not soup:
        return []
    posts = []
    for row in soup.select("tr"):
        title_td = row.select_one("td.li_sbj")
        date_td  = row.select_one("td.li_date")
        if not title_td or not date_td:
            continue
        # 날짜: "2026-09-0721:56" 형식 → 앞 10자만
        date_str = date_td.get_text(strip=True)[:10]
        if not is_yday(date_str):
            continue
        # 링크: 행의 첫 번째 a
        a = row.select_one("a[href*='read']")
        if not a:
            continue
        title = title_td.get_text(strip=True)
        href  = a.get("href", "")
        url   = urljoin("http://web.humoruniv.com/board/humor/list.html", href)
        posts.append(mk(title, url, date_str))
    return posts


def scrape_clien():
    """클리앙 clien.net — 모두의공원"""
    soup = get("https://www.clien.net/service/board/park?od=T33&po=0&category=0&groupCd=clien_all",
               ref="https://www.clien.net/")
    if not soup:
        return []
    posts = []
    for row in soup.select("div.list_item"):
        a = row.select_one("a[href*='/service/board/park/']")
        if not a:
            continue
        title_el = a.select_one("span.subject_fixed, .list_subject") or a
        title    = title_el.get_text(strip=True)
        href     = a.get("href", "")
        url      = ("https://www.clien.net" + href) if href.startswith("/") else href
        date_el  = row.select_one("span.timestamp, time")
        if date_el:
            date_str = (date_el.get("title", "") or date_el.get_text(strip=True))[:10]
        else:
            date_str = ""
        if not is_yday(date_str):
            continue
        view_el = row.select_one(".hit, .list_hit")
        posts.append(mk(title, url, date_str,
                        views=n(view_el.text if view_el else 0)))
    return posts


def scrape_bobaedream():
    """보배드림 bobaedream.co.kr — 베스트
    실제 목록 테이블은 table.bbs_list 가 아니라 table#boardlist, 행은 tr[itemscope].
    날짜는 오늘이면 "16:39" 시각만, 오늘이 아니면 "09/08"(MM/DD, 연도 없음)로 나온다.
    게시량이 많아서 1~2페이지론 어제 글까지 못 미침(실측 6~7페이지부터 어제, 17페이지
    근처부터 그제) — 그래서 다른 고빈도 게시판들과 같은 "어제보다 오래된 글 나오면 멈춤"
    패턴으로 페이지를 더 넉넉히 넘긴다.
    """
    posts = []
    for page in range(1, 20):
        url = f"https://www.bobaedream.co.kr/list?code=best&page={page}"
        soup = get(url, ref="https://www.bobaedream.co.kr/")
        if not soup:
            break
        rows = soup.select("table#boardlist tr[itemscope]")
        if not rows:
            break
        passed_yday = False
        for row in rows:
            a = row.select_one("a.bsubject")
            if not a:
                continue
            date_el  = row.select_one("td.date")
            date_str = date_el.get_text(strip=True) if date_el else ""
            d = parse_date(date_str)
            if d is not None and d < YESTERDAY and (TODAY - d).days <= 3:
                passed_yday = True
                continue
            if d != YESTERDAY:
                continue
            title = a.get_text(strip=True)
            href  = a.get("href", "")
            url_a = urljoin("https://www.bobaedream.co.kr/list", href)
            view_el = row.select_one("td.count")
            posts.append(mk(title, url_a, date_str,
                            views=n(view_el.text if view_el else 0)))
        if passed_yday:
            break
    return posts


def scrape_inven():
    """인벤 inven.co.kr — 베스트(이슈) 일간 랭킹
    https://www.inven.co.kr/best/issue/daily : "일간 베스트"라 아직 표가 덜 난 오늘 글보다
    어제 하루 종일 추천받은 글이 상위권을 대부분 차지함 -> 페이지네이션 없이 1페이지만으로도
    어제 글이 충분히 잡힘 (날짜는 이미 지난 글이면 MM-DD, 당일 글이면 HH:MM으로 표시).
    """
    soup = get("https://www.inven.co.kr/best/issue/daily", ref="https://www.inven.co.kr/")
    if not soup:
        return []
    posts = []
    for row in soup.select("table tr"):
        a = row.select_one("td.title a.link")
        if not a:
            continue
        title    = a.get_text(strip=True)
        href     = a.get("href", "")
        url_a    = href if href.startswith("http") else "https://www.inven.co.kr" + href
        date_el  = row.select_one("td.date")
        date_str = date_el.get_text(strip=True) if date_el else ""
        if not is_yday(date_str):
            continue
        view_el = row.select_one("td.view")
        posts.append(mk(title, url_a, date_str,
                        views=n(view_el.text if view_el else 0)))
    return posts


def scrape_pann():
    """네이트판 — 구 URL(pann.nate.com/talk)은 실제 글 목록이 없는 허브 페이지라 원래부터 0건.
    실제 인기글은 pann.nate.com/talk/ranking/d (일간 랭킹)에 있음. 게시글 각각엔 작성
    날짜가 없지만, 페이지 자체가 "어제 하루"를 통째로 집계한 랭킹이라(오늘 접속하면
    `<title>`에 "일간 랭킹 : 2026.09.08"처럼 어제 날짜가 박혀 나옴) 그 날짜가 우리가
    찾는 YSTR과 일치하는지만 확인하면 개별 글 날짜 없이도 통째로 수집해도 안전함
    (82쿡/인벤과 같은 "게시판 자체가 이미 날짜로 스코프된 목록" 패턴).
    페이지는 1,2 두 페이지뿐(그 이상은 다시 1페이지로 돌아감).
    """
    posts = []
    for page in (1, 2):
        url = f"https://pann.nate.com/talk/ranking/d?page={page}"
        soup = get(url, ref="https://pann.nate.com/talk/ranking")
        if not soup or not soup.title:
            continue
        m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", soup.title.get_text())
        if not m or f"{m.group(1)}-{m.group(2)}-{m.group(3)}" != YSTR:
            continue
        for li in soup.select("ul.post_wrap li"):
            a = li.select_one("dl dt h2 a")
            if not a:
                continue
            title = a.get("title", "") or a.get_text(strip=True)
            href  = a.get("href", "")
            url_a = urljoin("https://pann.nate.com/talk/ranking/d", href)
            view_el = li.select_one("dd.info span.count")
            rcm_el  = li.select_one("dd.info span.rcm")
            cmt_el  = li.select_one("span.reple-num")
            posts.append(mk(title, url_a, YSTR,
                            views=n(view_el.text if view_el else 0),
                            comments=n(cmt_el.text if cmt_el else 0),
                            likes=n(rcm_el.text if rcm_el else 0)))
    return posts


def scrape_mlbpark():
    """엠엘비파크 mlbpark.donga.com — 자유게시판(bullpen)
    (재확인 결과 SPA 얘기는 옛말이고 지금은 정적 HTML에 목록이 그대로 옴)
    글 목록 행 안의 상세보기 링크 href에 있는 `id=` 쿼리파라미터가 "YYYYMMDDHHnnnnnnnn"
    형태라 앞 8자리가 곧 작성일자 — 화면에 보이는 날짜 칸은 오늘 글이면 시각만("17:06:41")
    나와서 그대로는 못 쓰지만, 이 id 앞자리로 대체하면 DayRollback 없이도 정확한 날짜를
    알 수 있다. 다만 이 게시판은 하루 게시량이 매우 많아(하루치가 offset 1500 이상,
    즉 50페이지 이상) 1페이지씩 순서대로 넘기며 어제 글을 찾는 건 비효율적이라, 먼저
    이진탐색으로 "오늘→어제" 경계 오프셋을 찾은 뒤 그 지점부터 정해진 페이지 수만큼만
    수집한다(루리웹과 같은 이유로 하루 전체를 다 긁진 않고 근처 표본만 담음).
    """
    def first_date_at(p):
        soup = get(f"https://mlbpark.donga.com/mp/b.php?p={p}&m=list&b=bullpen"
                   "&query=&select=&subquery=&subselect=&user=",
                   ref="https://mlbpark.donga.com/mp/b.php?b=bullpen")
        if not soup:
            return None
        table = soup.select_one("table.tbl_type01")
        if not table:
            return None
        for row in table.select("tr"):
            a = row.select_one("td.t_left div.tit a.txt")
            if a:
                m = re.search(r"id=(\d{8})", a.get("href", ""))
                if m:
                    return m.group(1)
        return None

    ystr_compact = YSTR.replace("-", "")
    today_compact = TODAY.strftime("%Y%m%d")

    lo, hi = 1, 4000
    while lo < hi:
        mid = (lo + hi) // 2
        d = first_date_at(mid)
        if d is None or d >= today_compact:
            lo = mid + 1
        else:
            hi = mid
    start_p = max(1, lo - 30)

    posts = []
    for i in range(20):
        p = start_p + i * 30
        soup = get(f"https://mlbpark.donga.com/mp/b.php?p={p}&m=list&b=bullpen"
                   "&query=&select=&subquery=&subselect=&user=",
                   ref="https://mlbpark.donga.com/mp/b.php?b=bullpen")
        if not soup:
            break
        table = soup.select_one("table.tbl_type01")
        rows = table.select("tr") if table else []
        if not rows:
            break
        passed_yday = False
        for row in rows:
            a = row.select_one("td.t_left div.tit a.txt")
            if not a:
                continue
            m = re.search(r"id=(\d{8})", a.get("href", ""))
            if not m:
                continue
            date_prefix = m.group(1)
            if date_prefix < ystr_compact:
                passed_yday = True
                continue
            if date_prefix != ystr_compact:
                continue
            title = a.get("alt", "") or a.get_text(strip=True)
            url_a = urljoin("https://mlbpark.donga.com/mp/b.php", a.get("href", ""))
            date_el = row.select_one("td span.date")
            view_el = row.select_one("td.t_right span.viewV")
            posts.append(mk(title, url_a, date_el.get_text(strip=True) if date_el else YSTR,
                            views=n(view_el.text if view_el else 0)))
        if passed_yday:
            break
    return posts


def scrape_gasengi():
    """가생이닷컴 gasengi.com — 유머(bo_table=humor04)
    bo_table=humor 은 더 이상 존재하지 않는 게시판(정확한 코드는 humor04)이라 항상 오류 페이지였음.
    그누보드5/부트스트랩 스킨으로 바뀌어 제목/날짜 클래스도 td_subject/td_datetime이 아님.
    1페이지는 당일(HH:MM) 글 위주라 2페이지까지 훑는다.
    """
    posts = []
    for page in (1, 2):
        url = f"https://www.gasengi.com/main/board.php?bo_table=humor04&page={page}"
        soup = get(url, ref="https://www.gasengi.com/")
        if not soup:
            continue
        for row in soup.select("table tr"):
            if "table-primary" in (row.get("class") or []):
                continue
            a = row.select_one("td.text-start a.link-body-emphasis")
            if not a:
                continue
            title    = a.get_text(strip=True)
            href     = a.get("href", "")
            url_a    = href if href.startswith("http") else "https://www.gasengi.com" + href
            date_tds = row.select("td.small")
            date_str = date_tds[-1].get_text(strip=True) if date_tds else ""
            if not is_yday(date_str):
                continue
            view_str = date_tds[0].get_text(strip=True) if len(date_tds) > 1 else "0"
            posts.append(mk(title, url_a, date_str, views=n(view_str)))
    return posts


# ── 커뮤니티 목록 ─────────────────────────────────────────────────────────────

COMMUNITIES = [
    ("에스엘알클럽", "📸", scrape_slr),
    ("개드립",       "😂", scrape_dogdrip),
    ("이토랜드",     "😄", scrape_etoland),
    ("뽐뿌",         "💰", scrape_ppomppu),
    ("오늘의유머",   "😆", scrape_todayhumor),
    ("루리웹",       "🎮", scrape_ruliweb),
    ("와이고수",     "💪", scrape_ygosu),
    ("더쿠",         "💜", scrape_theqoo),
    ("인스티즈",     "🌟", scrape_instiz),
    ("딴지일보",     "📰", scrape_ddanzi),
    ("82쿡",         "🍳", scrape_cook82),
    ("디시인사이드", "🖼",  scrape_dcinside),
    ("에펨코리아",   "⚽", scrape_fmkorea),
    ("웃긴대학",     "🤣", scrape_humoruniv),
    ("클리앙",       "💻", scrape_clien),
    ("보배드림",     "🚗", scrape_bobaedream),
    ("인벤",         "⚔",  scrape_inven),
    ("네이트판",     "💬", scrape_pann),
    ("엠엘비파크",   "⚾", scrape_mlbpark),
    ("가생이닷컴",   "🌏", scrape_gasengi),
]


# ── HTML 생성 ─────────────────────────────────────────────────────────────────

def generate_html(results: list) -> str:
    total = sum(len(r["posts"]) for r in results)
    ok    = sum(1 for r in results if not r["error"] and r["posts"])
    err   = sum(1 for r in results if r["error"])

    def render_rows(posts, show_source=False):
        rows = ""
        for p in posts:
            meta = []
            if p["views"]:    meta.append(f"👁 {p['views']:,}")
            if p["comments"]: meta.append(f"💬 {p['comments']:,}")
            if p["likes"]:    meta.append(f"❤ {p['likes']:,}")
            meta_str = " &nbsp;·&nbsp; ".join(meta)
            src = f'<span class="badge">{p["_src_emoji"]} {p["_src_name"]}</span> ' if show_source else ""
            rows += f"""
                <li>
                  {src}<a href="{p['url']}">{p['title']}</a>
                  {f'<span class="meta">{meta_str}</span>' if meta_str else ''}
                </li>"""
        return rows

    sections = ""
    flagged_all = []
    sec_i = 0
    for r in results:
        name  = r["name"]
        emoji = r["emoji"]
        posts = r["posts"]

        if r["error"]:
            sections += f"""
            <div class="section error-section">
              <div class="sec-head"><span class="emoji">{emoji}</span>{name}
                <span class="badge badge-err">오류</span>
              </div>
              <div class="err-msg">{r['error']}</div>
            </div>"""
            continue

        for p in posts:
            if is_flagged(p["title"]):
                flagged_all.append({**p, "_src_name": name, "_src_emoji": emoji})
        posts = [p for p in posts if not is_flagged(p["title"])]

        if not posts:
            sections += f"""
            <div class="section empty-section">
              <div class="sec-head"><span class="emoji">{emoji}</span>{name}
                <span class="badge badge-empty">어제 글 없음</span>
              </div>
            </div>"""
            continue

        sections += f"""
            <details class="section" id="sec-{sec_i}">
              <summary class="sec-head">
                <span class="emoji">{emoji}</span>{name}
                <span class="badge">{len(posts)}건</span>
              </summary>
              <ul class="post-list">{render_rows(posts)}
              </ul>
            </details>"""
        sec_i += 1

    if flagged_all:
        sections += f"""
            <details class="section" id="sec-flagged">
              <summary class="sec-head">
                <span class="emoji">⚠️</span>주의 표현 포함 글
                <span class="badge">{len(flagged_all)}건</span>
              </summary>
              <ul class="post-list">{render_rows(flagged_all, show_source=True)}
              </ul>
            </details>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>커뮤니티 베스트 {YSTR}</title>
<style>
  :root {{
    --bg: #f0f2f5; --card: #fff; --text: #1a1a2e; --sub: #6c757d;
    --head-bg: #1a1a2e; --head-text: #fff;
    --badge: #e9ecef; --badge-text: #495057;
    --link: #1565c0; --link-hover: #0d47a1;
    --border: #dee2e6; --err: #fff3cd; --meta: #888;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #0d1117; --card: #161b22; --text: #c9d1d9; --sub: #8b949e;
      --head-bg: #010409; --head-text: #c9d1d9;
      --badge: #21262d; --badge-text: #8b949e;
      --link: #58a6ff; --link-hover: #79b8ff;
      --border: #30363d; --err: #2d2a1e; --meta: #6e7681;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo',sans-serif; font-size: 14px; line-height: 1.6; }}
  .header {{ background: var(--head-bg); color: var(--head-text); padding: 20px 24px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
  .header .meta {{ font-size: 12px; opacity: .7; }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 20px 16px; }}
  .summary {{ display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
  .stat {{ background: var(--card); border-radius: 8px; padding: 10px 16px; font-size: 13px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .stat strong {{ display: block; font-size: 22px; font-weight: 700; color: var(--link); }}
  .section {{ background: var(--card); border-radius: 8px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow: hidden; }}
  .error-section, .empty-section {{ opacity: .5; }}
  .sec-head {{ background: var(--head-bg); color: var(--head-text); padding: 9px 14px; font-size: 13px; font-weight: 700; display: flex; align-items: center; gap: 6px; cursor: pointer; list-style: none; }}
  .sec-head::-webkit-details-marker {{ display: none; }}
  .sec-head::before {{ content: "▸"; font-size: 11px; }}
  details[open] > .sec-head::before {{ content: "▾"; }}
  .emoji {{ font-size: 16px; }}
  .badge {{ margin-left: auto; background: rgba(255,255,255,.15); color: #fff; border-radius: 20px; padding: 1px 10px; font-size: 11px; font-weight: 600; }}
  .badge-err   {{ background: #e74c3c; }}
  .badge-empty {{ background: rgba(255,255,255,.08); }}
  .post-list {{ list-style: none; }}
  .post-list li {{ padding: 8px 14px; border-bottom: 1px solid var(--border); display: flex; align-items: baseline; gap: 8px; }}
  .post-list li:last-child {{ border-bottom: none; }}
  .post-list a {{ color: var(--link); text-decoration: none; flex: 1; word-break: break-word; }}
  .post-list a:hover {{ color: var(--link-hover); text-decoration: underline; }}
  .meta {{ font-size: 11px; color: var(--meta); white-space: nowrap; }}
  .err-msg {{ padding: 10px 14px; font-size: 12px; color: #856404; background: var(--err); }}
  .footer {{ text-align: center; color: var(--sub); font-size: 11px; margin-top: 24px; padding-bottom: 24px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🗞 커뮤니티 베스트</h1>
  <div class="meta">기준: {YSTR} (어제) &nbsp;|&nbsp; 수집 시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')}</div>
</div>
<div class="wrap">
  <div class="summary">
    <div class="stat"><strong>{total}</strong>건 수집</div>
    <div class="stat"><strong>{ok}</strong>개 커뮤니티 성공</div>
    <div class="stat"><strong>{err}</strong>개 오류</div>
  </div>
  {sections}
  <div class="footer">커뮤니티 베스트 자동 수집 · 제목 중복 제거 적용</div>
</div>
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
    document.querySelectorAll('details.section[id]').forEach(function(el) {{
      el.open = !!state[el.id];
    }});
  }}
  document.addEventListener('toggle', function(ev) {{
    var el = ev.target;
    if (el.tagName === 'DETAILS' && el.classList.contains('section') && el.id) {{
      var state = loadState();
      state[el.id] = el.open;
      saveState(state);
    }}
  }}, true);
  applyState();
  window.addEventListener('pageshow', applyState);
}})();
</script>
</body>
</html>"""


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print(f"=== 커뮤니티 베스트 수집  기준: {YSTR} ===\n")
    seen_titles: set = set()
    results = []

    for name, emoji, fn in COMMUNITIES:
        print(f"[{name}] 수집 중...")
        error = None
        posts = []
        try:
            raw = fn()
            for p in raw:
                key = re.sub(r"\s+", "", p["title"]).lower()
                if key and key not in seen_titles:
                    seen_titles.add(key)
                    posts.append(p)
            dup = len(raw) - len(posts)
            print(f"  → {len(posts)}건  (중복 제거 {dup}건)")
        except Exception as e:
            error = str(e)
            print(f"  ✘ 오류: {e}")
        results.append({"name": name, "emoji": emoji, "posts": posts, "error": error})
        time.sleep(0.8)

    print(f"\n총 {sum(len(r['posts']) for r in results)}건 수집 완료")
    html = generate_html(results)
    REPORT.write_text(html, encoding="utf-8")
    print(f"저장: {REPORT}")

    import json
    (OUT_DIR / "report_data.json").write_text(
        json.dumps({"date": YSTR, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if "--no-open" not in sys.argv:
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", str(REPORT)])
        print("✅ 브라우저에서 열었습니다.")


if __name__ == "__main__":
    main()
