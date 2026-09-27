"""Versioned CN scenarios. No Qlib or database dependency in this module."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from .cn_schema import check, validate_shapes


def dec(value):
    return Decimal(str(value))


CN_SYNTHETIC_DATASET_ID = "cn-current-synthetic"


def snapshot_content_digest(path) -> dict:
    """Logical content digest: data trees only, ignoring scenario/config manifests.

    `scenario.json` describes the configuration and `content.json` records this digest, so
    neither may feed the digest; otherwise the version would move with configuration changes
    (GOV-CONFIG) instead of describing the data.
    """
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"snapshot path is not a directory: {root}")
    ignored = {"content.json", "scenario.json"}
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name not in ignored)
    outer = hashlib.sha256()
    size = 0
    for file in files:
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        outer.update(f"{file.relative_to(root).as_posix()}\n{digest}\n".encode())
        size += file.stat().st_size
    return {"schema_version": 1, "basis": "files_sha256", "digest": outer.hexdigest(),
            "file_count": len(files), "bytes": size}


def ensure_snapshot_content(path) -> dict:
    """Write or refresh `content.json`; the digest is always recomputed from the files."""
    root = Path(path)
    computed = snapshot_content_digest(root)
    manifest = root / "content.json"
    recorded = None
    if manifest.is_file():
        try:
            recorded = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recorded = None
    if recorded and recorded.get("digest") == computed["digest"] and recorded.get("basis") == computed["basis"]:
        return recorded
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    record = {**computed, "registered_at": stamp,
              "previous_digest": (recorded or {}).get("digest"),
              "note": "synthetic snapshot; digest covers file bytes only, not market truth"}
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def rdagent_snapshot_path(fingerprint: str, home=None) -> Path:
    """Container snapshot used by the RD-Agent factor template (same scenario data)."""
    base = Path(home).expanduser() if home else Path.home()
    return base / ".qlib/qlib_data/qwb_cn_current" / fingerprint[:12]


class ProjectRootNotFound(RuntimeError):
    """An explicit project root that is not a checkout is refused.

    Falling back to the installed checkout would run engine/stub work against the real
    working tree — that is how test leftovers (`runs/`) appeared in the repository root.
    """


def _looks_like_checkout(candidate: Path) -> bool:
    try:
        return (candidate / "configs/cn/profile.json").is_file() and (candidate / "scripts").is_dir()
    except OSError:
        return False


def discover_project_root(explicit=None) -> Path:
    """Locate the Qlib checkout that owns configs/cn/profile.json and scripts/.

    Without an explicit candidate the installed checkout is the intended answer. With one,
    an unmarked directory (a test sandbox, a data directory) must not resolve to the real
    checkout, so the mismatch is raised instead of silently ignored.
    """
    here = Path(__file__).resolve()
    if explicit:
        candidate = Path(explicit)
        if _looks_like_checkout(candidate):
            return candidate.resolve()
        raise ProjectRootNotFound(
            f"explicit project root is not a Qlib checkout: {candidate} "
            f"(needs configs/cn/profile.json and scripts/); refusing to fall back to "
            f"{here.parents[2].resolve()}")
    candidates = []
    if os.environ.get("QWB_REPO_ROOT"):
        candidates.append(Path(os.environ["QWB_REPO_ROOT"]))
    candidates.extend(here.parents)
    candidates.append(Path.cwd())
    for candidate in candidates:
        if _looks_like_checkout(candidate):
            return candidate.resolve()
    return here.parents[2].resolve()


def default_profile_path(explicit=None) -> Path:
    env = os.environ.get("QWB_CN_PROFILE")
    if env:
        return Path(env).expanduser().resolve()
    return discover_project_root(explicit) / "configs/cn/profile.json"
CN_SYNTHETIC_SOURCE_INSTANCE = "qlib-cn-attempt"


def load_profile(path):
    path = Path(path).resolve()
    index = json.loads(path.read_text())
    check(index, {"schema_version":"v1", **{k:"text" for k in ("rules","account","calendar","research")}}, "profile")
    if index.get("schema_version") != 1:
        raise ValueError("Unsupported CN profile schema")
    bundle = {key: json.loads((path.parent / index[key]).read_text())
              for key in ("rules", "account", "calendar", "research")}
    validate(bundle)
    bundle["fingerprint"] = scenario_fingerprint(bundle)
    bundle.update(scenario_identities(bundle))
    return bundle


# Derived identity keys are excluded when re-verifying a recorded scenario.
DERIVED_IDENTITY_KEYS = ("fingerprint", "execution_fingerprint", "evaluation_fingerprint",
                         "experiment_id", "data_identity")


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scenario_fingerprint(bundle) -> str:
    """Scenario identity over the recorded configuration, ignoring derived identity keys."""
    return _digest({key: value for key, value in bundle.items() if key not in DERIVED_IDENTITY_KEYS})


def scenario_identities(bundle) -> dict:
    """Split one scenario into comparison identities (see RESULT_CONTRACT 身份分层).

    The full `fingerprint` still keys data materialisation and templates; ranking uses the
    split below so that changing research parameters stops blocking a fair comparison.
    """
    rules, account, calendar, research = (bundle[k] for k in ("rules", "account", "calendar", "research"))
    execution = _digest({
        "rules": rules, "account": account, "calendar": calendar,
        "market": research["market"], "benchmark": research["benchmark"],
        "execution": research["execution"], "synthetic": research["synthetic"],
    })
    evaluation = _digest({
        "date_range": research["date_range"], "segments": research["segments"],
        "label": research["label"], "market": research["market"], "benchmark": research["benchmark"],
        "quality": research["quality"], "annualization": research.get("annualization"),
    })
    experiment = _digest({"model": research["model"], "strategy": research["strategy"],
                          "agent": research.get("agent")})
    data = _digest({
        "calendar": calendar, "fixture": research["fixture"], "market": research["market"],
        "benchmark": research["benchmark"], "date_range": research["date_range"],
        "tick_size": rules["tick_size"], "boards": rules["boards"],
    })
    return {"execution_fingerprint": execution, "evaluation_fingerprint": evaluation,
            "experiment_id": experiment, "data_identity": data}


def validate(bundle):
    validate_shapes(bundle)
    rules, account, calendar, research = (bundle[k] for k in ("rules", "account", "calendar", "research"))
    expected = {
        'rules': 'schema_version id as_of effective_from timezone scope tick_size share_settlement_days fees boards sources verification_notes',
        'account': 'schema_version commission_both minimum_commission commission_includes_regulatory_fees commission_includes_transfer_fee initial_cash assumptions',
        'calendar': 'schema_version id timezone coverage weekdays closed_ranges sessions sources',
        'research': 'schema_version mode synthetic enabled_boards supported_status market benchmark data_path date_range segments label execution strategy model quality fixture agent annualization unsupported',
    }
    for name, names in expected.items():
        if set(bundle[name]) != set(names.split()):
            raise ValueError(f'Unknown or missing {name} fields: {set(bundle[name]) ^ set(names.split())}')
    if set(research['execution']) != {'deal_price', 'volume_participation', 'slippage_bps', 'forbid_all_trade_at_limit', 'require_factor'}:
        raise ValueError('Unknown or missing execution parameter')
    for key in ('as_of', 'effective_from'):
        date.fromisoformat(rules[key])
    if any(x.get("schema_version") != 1 for x in (rules, account, calendar, research)):
        raise ValueError("Unsupported configuration schema")
    if research["mode"] != "current_rules_counterfactual" or research["synthetic"] is not True:
        raise ValueError("This adapter is verified only for synthetic current-rule counterfactual research")
    if rules["effective_from"] > rules["as_of"]:
        raise ValueError("Rules are not effective on as_of")
    if rules["share_settlement_days"] != 1:
        raise ValueError("Only next-trading-day share settlement is implemented")
    if not account["commission_includes_regulatory_fees"]:
        raise ValueError("Net commission requires a separate verified regulatory-fee schedule")
    for value in (account['commission_includes_regulatory_fees'], account['commission_includes_transfer_fee'],
                  research['execution']['forbid_all_trade_at_limit']):
        if type(value) is not bool:
            raise ValueError('Configuration switches must be JSON booleans')
    for value in (account["commission_both"], rules["fees"]["stamp_sell"], rules["fees"]["transfer_both"]):
        if not dec(value).is_finite() or not 0 <= dec(value) < 1:
            raise ValueError("Invalid fee rate")
    if not dec(account['minimum_commission']).is_finite() or dec(account["minimum_commission"]) < 0 or account["initial_cash"] <= 0:
        raise ValueError("Invalid account cash/commission")
    if not 0 < dec(research["execution"]["volume_participation"]) <= 1:
        raise ValueError("Participation must be in (0,1]")
    if not 0 <= dec(research["execution"]["slippage_bps"]) < 10000:
        raise ValueError("Invalid slippage")
    if research["execution"]["deal_price"] != "close":
        raise ValueError("Only previous-session signal / current close execution has been verified")
    if research["execution"]["require_factor"] is not True:
        raise ValueError("Missing factors must not silently disable share rounding")
    if not set(research["enabled_boards"]) <= rules["boards"].keys():
        raise ValueError("Unknown board")
    for board in rules["boards"].values():
        if not 0 < dec(board["limit"]) < 1 or min(board["buy_min"], board["step"], board["max_order"]) <= 0:
            raise ValueError("Invalid board rule")
    if research["supported_status"] != ["normal"]:
        raise ValueError("ST/IPO/delisting states require a verified state data adapter")
    if research['fixture']['board'] not in research['enabled_boards']:
        raise ValueError('Fixture board is disabled')
    if research['strategy']['topk'] > research['fixture']['stock_count'] or research['strategy']['n_drop'] > research['strategy']['topk']:
        raise ValueError('Invalid portfolio size')
    if research['strategy']['topk'] < 1 or research['strategy']['n_drop'] < 0:
        raise ValueError('Invalid portfolio size')
    if any(type(v) is not int or v <= 0 for v in research['quality'].values()):
        raise ValueError('Quality thresholds must be positive integers')
    if research["label"]["expression"] != "Ref($close, -2)/Ref($close, -1) - 1" or research["label"]["future_bars"] != 2:
        raise ValueError("Changed label requires a reviewed horizon implementation")
    sessions(calendar, *research["date_range"])
    effective_segments(bundle)


def sessions(calendar, start, end):
    if not calendar["coverage"][0] <= str(start) <= str(end) <= calendar["coverage"][1]:
        raise ValueError("Calendar coverage missing; refusing weekday fallback")
    current, stop = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    result = []
    while current <= stop:
        day = current.isoformat()
        if current.weekday() in calendar["weekdays"] and not any(a <= day <= b for a, b in calendar["closed_ranges"]):
            result.append(day)
        current += timedelta(days=1)
    return result


def effective_segments(bundle):
    research = bundle["research"]
    days = sessions(bundle["calendar"], *research["date_range"])
    horizon = research["label"]["future_bars"]
    result = {}
    previous_end = None
    for name in ("train", "valid", "test"):
        start, end = research["segments"][name]
        if previous_end and start <= previous_end:
            raise ValueError("Overlapping research segments")
        selected = [d for i, d in enumerate(days) if start <= d <= end
                    and i + horizon < len(days) and days[i + horizon] <= end]
        if not selected:
            raise ValueError(f"No label-safe samples in {name}")
        result[name] = [selected[0], selected[-1]]
        previous_end = end
    return result


def fees(notional, side, bundle):
    if side not in ("buy", "sell"):
        raise ValueError("Unknown side")
    value = dec(notional)
    if not value.is_finite() or value < 0:
        raise ValueError("Invalid notional")
    account, schedule = bundle["account"], bundle["rules"]["fees"]
    quantum = dec(schedule["rounding_unit"])
    def rounded(x):
        return x.quantize(quantum, rounding=ROUND_HALF_UP)
    commission = max(value * dec(account["commission_both"]), dec(account["minimum_commission"])) if value else dec(0)
    transfer = value * dec(schedule["transfer_both"]) if not account["commission_includes_transfer_fee"] else dec(0)
    stamp = value * dec(schedule["stamp_sell"]) if side == "sell" else dec(0)
    # A research friction assumption; kept separate from taxes and commission.
    slippage = value * dec(bundle["research"]["execution"]["slippage_bps"]) / dec(10000)
    result = dict(commission=rounded(commission), transfer=rounded(transfer), stamp=rounded(stamp), slippage=rounded(slippage))
    result["total"] = sum(result.values(), dec(0))
    return result


def order_quantity(requested, board, side, available=None):
    quantity = int(dec(requested).to_integral_value(rounding=ROUND_DOWN))
    quantity = min(quantity, board["max_order"])
    if side == "sell" and available is not None:
        quantity = min(quantity, int(available))
        if quantity == int(available):  # liquidation may include the entire odd-lot balance
            return max(quantity, 0)
    if quantity < board["buy_min"]:
        return 0
    return board["buy_min"] + (quantity - board["buy_min"]) // board["step"] * board["step"]


def price_limits(reference, board, tick):
    quantum = dec(tick)
    ref = dec(reference)
    if quantum <= 0 or ref <= 0:
        raise ValueError('Invalid price or tick')
    lower, upper = ((ref * (1 + sign * dec(board['limit'])) / quantum).quantize(dec(1), rounding=ROUND_HALF_UP) * quantum
                    for sign in (-1, 1))
    return max(quantum, min(ref - quantum, lower)), max(ref + quantum, upper)


def quality_summary(metrics, trade_days, thresholds):
    missing = [k for k in ("IC", "Rank IC", "ICIR", "Rank ICIR")
               if metrics.get(k) is None or not dec(metrics[k]).is_finite()]
    reasons = (["missing_ic_metrics"] if missing else [])
    if trade_days < thresholds["min_trade_days"]:
        reasons.append("insufficient_trade_days")
    return {"research_valid": False if reasons else None, "missing_metrics": missing,
            "trade_days": trade_days, "reasons": reasons,
            "note": "No failure does not prove alpha; cross-sectional/time-series quality must also be checked."}
