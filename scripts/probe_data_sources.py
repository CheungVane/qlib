#!/usr/bin/env python3
"""免费数据源可用性与最新日期探测（因子研究用）。

契约见 docs/spec/DATA_SOURCES.md。只读网络请求：不下载数据包、不写入数据目录、
不读取密钥。每个来源独立失败，不影响其他来源，失败原因原样记录。

用法：
    python3 scripts/probe_data_sources.py
    python3 scripts/probe_data_sources.py --output docs/spec/evidence/xxx.json
    python3 scripts/probe_data_sources.py --baostock-python /path/to/venv/bin/python
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "qwb-data-source-probe/1.0 (research; read-only)"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Accept": "*/*",
}

BAOSTOCK_SNIPPET = r"""
import json
import time
import baostock as bs

# BaoStock blacklists by IP on concurrency: stay sequential and pause between queries.
PAUSE_SECONDS = 1.0

result = {"login": None, "latest_daily": None, "calendar_tail": None,
          "adjust_factors": None, "financial": None}
login = bs.login()
result["login"] = {"code": login.error_code, "message": login.error_msg}
try:
    rs = bs.query_history_k_data_plus("sh.600000", "date,code,close,volume,amount",
                                      start_date="2026-01-01", end_date="2026-12-31",
                                      frequency="d", adjustflag="3")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rows:
        result["latest_daily"] = {"first": rows[0], "last": rows[-1], "rows": len(rows)}
    time.sleep(PAUSE_SECONDS)
    cal = bs.query_trade_dates(start_date="2026-09-20", end_date="2026-10-02")
    cal_rows = []
    while cal.error_code == "0" and cal.next():
        cal_rows.append(cal.get_row_data())
    result["calendar_tail"] = cal_rows
    time.sleep(PAUSE_SECONDS)
    adj = bs.query_adjust_factor(code="sh.600000", start_date="2026-01-01", end_date="2026-12-31")
    adj_rows = []
    while adj.error_code == "0" and adj.next():
        adj_rows.append(adj.get_row_data())
    result["adjust_factors"] = {"count": len(adj_rows), "last": adj_rows[-1] if adj_rows else None}
    time.sleep(PAUSE_SECONDS)
    fin = bs.query_profit_data(code="sh.600000", year=2026, quarter=2)
    fin_rows = []
    while fin.error_code == "0" and fin.next():
        fin_rows.append(fin.get_row_data())
    result["financial"] = {"fields": fin.fields, "row": fin_rows[0] if fin_rows else None}
finally:
    bs.logout()
print(json.dumps(result, ensure_ascii=False))
"""


def fetch(url, *, headers=None, timeout=20, data=None):
    request = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return response.status, dict(response.headers), body


def fetch_json(url, *, headers=None, timeout=20):
    status, _, body = fetch(url, headers=headers, timeout=timeout)
    return status, json.loads(body.decode("utf-8"))


def probe_investment_data(timeout):
    status, release = fetch_json(
        "https://api.github.com/repos/chenditc/investment_data/releases/latest",
        headers=GITHUB_HEADERS, timeout=timeout)
    assets = {item["name"]: item["size"] for item in release.get("assets", [])}
    observed = {"release_tag": release.get("tag_name"), "published_at": release.get("published_at"),
                "assets": assets}
    manifest_url = next((item["browser_download_url"] for item in release.get("assets", [])
                         if item["name"] == "qlib_bin.manifest.json"), None)
    if manifest_url:
        _, manifest = fetch_json(manifest_url, timeout=timeout)
        observed["manifest"] = manifest
    return {"id": "FINV", "status": "ok", "license": "repo Apache-2.0; upstream data terms unverified",
            "observed": observed}


def probe_baostock(timeout, external_python=None):
    if external_python:
        completed = subprocess.run([external_python, "-c", BAOSTOCK_SNIPPET],
                                   capture_output=True, text=True, timeout=timeout * 6)
        if completed.returncode != 0:
            return {"id": "BAO", "status": "fail",
                    "observed": {"returncode": completed.returncode,
                                 "stderr_tail": completed.stderr.strip().splitlines()[-1:]},
                    "notes": ["external interpreter failed"]}
        return {"id": "BAO", "status": "ok", "observed": json.loads(completed.stdout.strip().splitlines()[-1]),
                "notes": ["verified through an isolated interpreter; path not recorded"]}
    try:
        import baostock  # noqa: F401
    except ImportError:
        return {"id": "BAO", "status": "skipped",
                "observed": {"importable": False},
                "notes": ["baostock not installed in this interpreter; "
                          "use --baostock-python <venv>/bin/python to verify"]}
    completed = subprocess.run([sys.executable, "-c", BAOSTOCK_SNIPPET],
                               capture_output=True, text=True, timeout=timeout * 6)
    return {"id": "BAO", "status": "ok" if completed.returncode == 0 else "fail",
            "observed": json.loads(completed.stdout.strip().splitlines()[-1]) if completed.returncode == 0
            else {"stderr_tail": completed.stderr.strip().splitlines()[-1:]},
            "notes": ["verified in the current interpreter"]}


def probe_eastmoney(timeout):
    headers = dict(BROWSER_HEADERS, Referer="https://quote.eastmoney.com/")
    observed = {"attempts": 0}
    errors = []
    for attempt in range(2):
        observed["attempts"] = attempt + 1
        try:
            _, _, body = fetch(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                "?secid=1.600000&fields1=f1,f2,f3,f4,f5,f6"
                "&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&beg=20260101&end=20500101",
                headers=headers, timeout=timeout)
            rows = ((json.loads(body.decode("utf-8")).get("data") or {}).get("klines") or [])
            observed["rows"] = len(rows)
            observed["first"] = rows[0] if rows else None
            observed["last"] = rows[-1] if rows else None
            break
        except Exception as error:  # noqa: BLE001 - flaky free endpoint
            errors.append(f"{type(error).__name__}: {error}")
    try:
        _, snapshot = fetch_json(
            "https://push2.eastmoney.com/api/qt/stock/get"
            "?secid=1.600000&fields=f57,f58,f84,f85,f116,f117", headers=headers, timeout=timeout)
        observed["snapshot"] = snapshot.get("data")
    except Exception as error:  # noqa: BLE001
        errors.append(f"snapshot {type(error).__name__}: {error}")
    if errors:
        observed["errors"] = errors
    status = "ok" if observed.get("last") else ("partial" if observed.get("snapshot") else "fail")
    return {"id": "EM", "status": status, "observed": observed,
            "notes": ["unofficial public endpoint; automated-collection terms unverified",
                      "flaky in practice: retries required"]}


def probe_csindex(timeout):
    status, headers, body = fetch(
        "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000300cons.xls",
        timeout=timeout)
    return {"id": "CSI", "status": "ok",
            "observed": {"http_status": status, "bytes": len(body),
                         "content_type": headers.get("Content-Type")},
            "notes": ["official index constituent file for CSI300"]}


def probe_yahoo(timeout):
    try:
        status, _, body = fetch(
            "https://query1.finance.yahoo.com/v8/finance/chart/600000.SS?range=5d&interval=1d",
            headers=BROWSER_HEADERS, timeout=timeout)
        payload = json.loads(body.decode("utf-8"))
        chart = payload.get("chart") or {}
        observed = {"http_status": status, "bytes": len(body),
                    "result_count": len(chart.get("result") or []),
                    "chart_error": chart.get("error")}
        return {"id": "YF", "status": "ok" if chart.get("result") else "partial",
                "observed": observed,
                "notes": ["non-official endpoint; earlier probe returned HTTP 429"]}
    except urllib.error.HTTPError as error:
        return {"id": "YF", "status": "fail",
                "observed": {"http_status": error.code},
                "notes": ["non-official endpoint; rate limiting observed"]}


def probe_qlib_example(timeout):
    _, release = fetch_json("https://api.github.com/repos/SunsetWolf/qlib_dataset/releases/latest",
                            headers=GITHUB_HEADERS, timeout=timeout)
    return {"id": "QLIB-EX", "status": "ok",
            "observed": {"release_tag": release.get("tag_name"),
                         "published_at": release.get("published_at"),
                         "assets": {item["name"]: item["size"] for item in release.get("assets", [])}},
            "notes": ["static snapshot; cannot satisfy a 2026-09 coverage requirement"]}


def probe_tushare():
    return {"id": "TS", "status": "skipped",
            "observed": {"token_present": False},
            "notes": ["registration and point thresholds must be checked on the official site; "
                      "no token is used by this probe"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write the JSON evidence to this path")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--baostock-python",
                        help="interpreter that has baostock installed (isolated venv)")
    args = parser.parse_args()

    probes = [
        ("FINV", lambda: probe_investment_data(args.timeout)),
        ("BAO", lambda: probe_baostock(args.timeout, args.baostock_python)),
        ("EM", lambda: probe_eastmoney(args.timeout)),
        ("CSI", lambda: probe_csindex(args.timeout)),
        ("YF", lambda: probe_yahoo(args.timeout)),
        ("QLIB-EX", lambda: probe_qlib_example(args.timeout)),
        ("TS", probe_tushare),
    ]
    sources = []
    for name, run in probes:
        try:
            record = run()
        except Exception as error:  # noqa: BLE001 - a broken free source must not stop the probe
            record = {"id": name, "status": "fail",
                      "observed": {"error": f"{type(error).__name__}: {error}"}}
        sources.append(record)
        print(f"{record['id']:9s} {record['status']:8s} "
              f"{json.dumps(record.get('observed', {}), ensure_ascii=False)[:120]}")

    report = {
        "probe": "free-data-sources",
        "contract": "docs/spec/DATA_SOURCES.md",
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": "local",
        "notes": ["read-only probe; no data package downloaded, no snapshot created",
                  "paths, hostnames and credentials are not recorded"],
        "sources": sources,
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
