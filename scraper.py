"""
每日更新纳指100场外基金的申购状态与代销单日上限。

数据源：天天基金移动端接口（非官方开放接口）
- 自动更新：status / agency_limit / dt_open / rate / nav / nav_date / size
- 手动维护：direct_limit（基金公司直销限额，接口无此字段）
接口失败时保留旧数据，不清空。
"""
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta

DATA_FILE = "data.json"
API = ("https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx"
       "?FCODE={code}&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
BJ = timezone(timedelta(hours=8))


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


def fetch(code):
    req = urllib.request.Request(API.format(code=code), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["Datas"]


def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    ok = 0
    for fund in data["funds"]:
        try:
            d = fetch(fund["code"])
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
