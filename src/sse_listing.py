"""Fetch recent 上市公告 (listing-for-trading notices) for local government
bonds from the Shanghai Stock Exchange's public disclosure API.

This exists to close a real gap in the issuance calendar: celma.org.cn's
"发行结果" (confirmed results, with coupon rate) lags actual auctions by
roughly a week. SSE publishes a listing notice the same day a bond's
existence/trading status is confirmed -- days earlier than celma. That
notice does NOT carry the coupon rate (its own PDF text explicitly defers
rate details to "发行公告及相关发行文件"), so this is a genuinely different,
weaker signal than a confirmed result: it only proves the bond was
successfully issued and is trading, not what rate it priced at. Treated
and labeled as such ("已上市，利率待补"), never blended into the "confirmed"
bucket.

API discovered by driving a real headless browser (Playwright) to
https://bond.sse.com.cn/disclosure/announ/ltb and capturing its own XHR
call -- the sqlId/params aren't documented anywhere public. If SSE changes
this endpoint again, that's the way to re-discover it.

Not persisted to a state_*.csv: this is fetched live at dashboard-build
time (see build_dashboard_plan.py), since it's only useful as of "right
now" and isn't the kind of history worth archiving the way the three main
celma channels are.
"""
import requests

from .classify import extract_province

SSE_QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
SSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://bond.sse.com.cn/disclosure/announ/ltb",
}
REQUEST_TIMEOUT = 15


def fetch_recent_listing_notices(date_start: str, date_end: str) -> list[dict]:
    """Returns a list of {securityAbbr, securityCode, province, sseDate,
    title} for local-government-bond 上市公告 published in
    [date_start, date_end] (each "YYYY-MM-DD"). Returns [] on any network
    or parsing failure -- this is a best-effort supplementary signal, not
    a required data path, so a failure here should never break the rest
    of the dashboard refresh."""
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "200",
        "sqlId": "BS_ZQ_GGLL",
        "securityCode": "",
        "bondType": "LOCAL_GOVERNMENT_BOND_BULLETIN",
        "title": "",
        "orgBulletinType": "",
        "sseDate": f"{date_start} 00:00:00",
        "sseDateEnd": f"{date_end} 23:59:59",
        "order": "sseDate|desc,securityCode|asc,bulletinId|asc",
    }
    try:
        resp = requests.get(SSE_QUERY_URL, params=params, headers=SSE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    rows = data.get("pageHelp", {}).get("data", [])
    out = []
    for row in rows:
        if row.get("bulletinType") != "上市公告":
            continue
        title = row.get("title", "")
        province, _ = extract_province(title)
        sse_date = (row.get("sseDate") or "").split(" ")[0]
        if not sse_date:
            continue
        out.append({
            "securityAbbr": row.get("securityAbbr"),
            "securityCode": row.get("securityCode"),
            "province": province,
            "sseDate": sse_date,
            "title": title,
        })
    return out
