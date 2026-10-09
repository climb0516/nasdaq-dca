"""
每日更新纳指100场外基金的申购状态、限额，以及综合评分所需的数据。

数据源：天天基金（非官方开放接口 / 网页）
- 申购状态与限额：status / agency_limit / dt_open / rate / nav / nav_date / size
- 用户数据：fav_count（自选人数）/ dt_count（近1月定投人数）/ avg_hold（平均持有天数）
- 份额变化：shares_now / shares_1y_ago / shares_date（持有人结构，半年报更新）
- 基金属性：mgmt_fee / custody_fee（年费率 %）/ tracking_error（年化跟踪误差 %）
- 手动维护：direct_limit（基金公司直销限额，接口无此字段）
任一数据源失败时保留该部分旧数据，不清空。
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta

DATA_FILE = "data.json"
MOB = "deviceid=Wap&plat=Wap&product=EFund&version=6.5.0&FCODE={code}"
API = ("https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx"
       "?FCODE={code}&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
API_USER = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNUniqueInfo?" + MOB
API_HOLDER = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHolderStructure?" + MOB
PAGE_BASIC = "https://fundf10.eastmoney.com/jbgk_{code}.html"
PAGE_TRACK = "https://fundf10.eastmoney.com/tsdata_{code}.html"
BJ = timezone(timedelta(hours=8))
HEADERS = {"User-Agent": "curl/8.7.1", "Accept": "*/*"}
PAUSE = 0.4  # 请求间隔，防止被限流


def parse_sgzt(sgzt):
    """'限大额(单日投资上限10元)' -> ('限额', 10)；'暂停申购' -> ('暂停', None)"""
    if not sgzt:
        return None, None
    m = re.search(r"上限([\d.]+)(万)?元", sgzt)
    limit = None
    if m:
        limit = float(m.group(1)) * (10000 if m.group(2) else 1)
        limit = int(limit) if limit == int(limit) else limit
    if "暂停" in sgzt:
        status = "暂停"
    elif "限" in sgzt:
        status = "限额"
    elif "开放" in sgzt:
        status = "开放"
    else:
        status = sgzt
    return status, limit


def get(url):
    time.sleep(PAUSE)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="ignore")


def get_datas(url):
    d = json.loads(get(url)).get("Datas")
    if not d:
        raise ValueError("Datas 为空")
    return d


def page_text(url):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", get(url)))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def update_user(fund):
    """自选人数、近1月定投人数、平均持有天数"""
    d = get_datas(API_USER.format(code=fund["code"]))
    fund["fav_count"] = num(d.get("FFAVORCOUNT"))
    fund["dt_count"] = num(d.get("DTCOUNT_Y"))
    fund["avg_hold"] = num(d.get("AVGHOLD"))


def update_holder(fund):
    """最新总份额与约一年前（两个半年报之前）的总份额"""
    rows = get_datas(API_HOLDER.format(code=fund["code"]))
    rows = sorted(rows, key=lambda r: r["FSRQ"], reverse=True)
    fund["shares_now"] = num(rows[0].get("ZFE"))
    fund["shares_date"] = rows[0].get("FSRQ")
    fund["shares_1y_ago"] = num(rows[2].get("ZFE")) if len(rows) > 2 else None


def update_fees(fund):
    """管理费率、托管费率（%/年）"""
    t = page_text(PAGE_BASIC.format(code=fund["code"]))
    m1 = re.search(r"管理费率 ([\d.]+)%", t)
    m2 = re.search(r"托管费率 ([\d.]+)%", t)
    if not (m1 and m2):
        raise ValueError("未解析到费率")
    fund["mgmt_fee"] = float(m1.group(1))
    fund["custody_fee"] = float(m2.group(1))


def update_tracking(fund):
    """年化跟踪误差（%）"""
    t = page_text(PAGE_TRACK.format(code=fund["code"]))
    m = re.search(r"同类平均跟踪误差 .*?纳斯达克\S*指数 ([\d.]+)%", t)
    if not m:
        raise ValueError("未解析到跟踪误差")
    fund["tracking_error"] = float(m.group(1))


def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    ok = 0
    for fund in data["funds"]:
        for name, fn in [("用户数据", update_user), ("份额", update_holder),
                         ("费率", update_fees), ("跟踪误差", update_tracking)]:
            try:
                fn(fund)
            except Exception as e:
                print(f"[KEEP] {fund['code']} {name} 保留旧数据: {e}")
        try:
            d = get_datas(API.format(code=fund["code"]))
            status, limit = parse_sgzt(d.get("SGZT"))
            if not status:
                raise ValueError("SGZT 为空")
            fund["status"] = status
            fund["status_raw"] = d.get("SGZT")
            # 暂停申购时接口里的"上限"无实际意义，置空
            fund["agency_limit"] = None if status == "暂停" else limit
            fund["dt_open"] = d.get("DTZT") == "1"
            fund["rate"] = d.get("RATE") or fund.get("rate")
            fund["nav"] = d.get("DWJZ") or fund.get("nav")
            fund["nav_date"] = d.get("FSRQ") or fund.get("nav_date")
            if d.get("ENDNAV"):
                fund["size"] = round(float(d["ENDNAV"]) / 1e8, 1)
            ok += 1
            print(f"[OK] {fund['code']} {fund['name']} {d.get('SGZT')}")
        except Exception as e:
            print(f"[KEEP] {fund['code']} {fund['name']} 保留旧数据: {e}")

    if ok:
        data["updated_at"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"done: {ok}/{len(data['funds'])} updated")


if __name__ == "__main__":
    main()
