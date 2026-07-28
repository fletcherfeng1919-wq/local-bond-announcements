"""Shared configuration and constants."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_HTML_DIR = DATA_DIR / "raw_html"
RAW_PDF_DIR = DATA_DIR / "raw_pdf"
STATE_ANNOUNCEMENTS_CSV = DATA_DIR / "state_announcements.csv"
STATE_PLANS_CSV = DATA_DIR / "state_plans.csv"
OUTPUT_DIR = PROJECT_ROOT / "output"
CHARTS_DIR = PROJECT_ROOT / "charts"

for d in (DATA_DIR, RAW_HTML_DIR, RAW_PDF_DIR, OUTPUT_DIR, CHARTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Polite crawling: delay range (seconds) between requests, and retry policy.
REQUEST_DELAY_RANGE = (1.5, 3.0)
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0

SITE_ROOT = "https://www.celma.org.cn"

# The two listing "channels" this project scrapes, keyed by celma.org.cn's
# internal channelId. Both are paginated identically: page 1 lives at
# zqsclb.jhtml?ad_code=87&channelId=<id>, subsequent pages at
# zqsclb_<n>.jhtml?ad_code=87&channelId=<id>. ad_code=87 == 全国 (nationwide,
# all provinces mixed in one feed) -- province is parsed out of each item's
# title/detail page rather than by filtering per-province, since a single
# nationwide feed avoids 36x redundant crawling.
LISTING_SOURCES = [
    {
        "name": "dfzfxjh",
        "label": "发行安排（月度/季度发行计划）",
        "channel_id": "192",
        "doc_type": "plan",
        "detail_url_prefix": "/dfzfxjh/",
    },
    {
        "name": "fxqgg",
        "label": "发行前公告（单期正式发行公告）",
        "channel_id": "193",
        "doc_type": "announcement",
        "detail_url_prefix": "/fxqgg/",
    },
]

FIRST_PAGE_TPL = SITE_ROOT + "/zqsclb.jhtml?ad_code=87&channelId={channel_id}"
PAGE_TPL = SITE_ROOT + "/zqsclb_{n}.jhtml?ad_code=87&channelId={channel_id}"

# Province / municipality-with-separate-planning name -> celma.org.cn ad_code.
# Sourced from the region dropdown on the listing pages. Kept even though we
# crawl the nationwide (ad_code=87) feed, because titles are matched against
# this name list to recover which region an item belongs to.
PROVINCES = {
    "北京市": "11", "天津市": "12", "河北省": "13", "山西省": "14",
    "内蒙古自治区": "15", "辽宁省": "21", "大连市": "2102", "吉林省": "22",
    "黑龙江省": "23", "上海市": "31", "江苏省": "32", "浙江省": "33",
    "宁波市": "3302", "安徽省": "34", "福建省": "35", "厦门市": "3502",
    "江西省": "36", "山东省": "37", "青岛市": "3702", "河南省": "41",
    "湖北省": "42", "湖南省": "43", "广东省": "44", "深圳市": "4403",
    "广西壮族自治区": "45", "海南省": "46", "重庆市": "50", "四川省": "51",
    "贵州省": "52", "云南省": "53", "西藏自治区": "54", "陕西省": "61",
    "甘肃省": "62", "青海省": "63", "宁夏回族自治区": "64",
    "新疆维吾尔自治区": "65", "新疆生产建设兵团": "66",
}
# Longest name first, so substring search doesn't stop at a short prefix
# (e.g. must try "新疆生产建设兵团" before "新疆维吾尔自治区" is ruled out).
PROVINCE_NAMES_BY_LEN_DESC = sorted(PROVINCES.keys(), key=len, reverse=True)

VALID_TERMS = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y"]

# Bond category: the three top-level buckets the user wants kept separate.
# Derived per-tranche from the 债券名称 table cell (or, failing that, from
# title keywords), never mixed together in downstream stats.
CATEGORY_NEW_GENERAL = "new_general"
CATEGORY_NEW_SPECIAL = "new_special"
CATEGORY_REFINANCING = "refinancing"
CATEGORY_LABELS = {
    CATEGORY_NEW_GENERAL: "一般新增债券",
    CATEGORY_NEW_SPECIAL: "专项新增债券",
    CATEGORY_REFINANCING: "再融资债券",
}

# Statutory floor: bond issuers must publish a pre-issuance announcement at
# least 5 workdays before bidding (财库〔2020〕43号).
STATUTORY_MIN_WORKDAYS = 5
