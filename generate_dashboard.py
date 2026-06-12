#!/usr/bin/env python3
"""
Broker's Pulse — static dashboard generator.

BACKEND WORKFLOW:
  1. Drop NSE report files into  data/reports/   (1A / 1C / 3B / 4B /
     registered client accounts / broker time-series — CSV, XLS, XLSX, HTML)
  2. Run:  python generate_dashboard.py
  3. Open / host the produced  index.html  — a single self-contained,
     fully interactive page. No server required.
"""

import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
REPORTS_DIR = ROOT / "data" / "reports"
OUTPUT = ROOT / "index.html"

TARGET_RATE = 80.0

# ═══════════════════════════════════════════════════════════════════
# PARSERS (battle-tested in the Streamlit app)
# ═══════════════════════════════════════════════════════════════════

def load_raw(path: Path) -> pd.DataFrame:
    b = path.read_bytes()
    name = path.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(b))
    if name.endswith((".html", ".htm")):
        return _html_tables(b.decode("utf-8", errors="ignore"))
    if name.endswith(".xls"):
        head = b[:500].lstrip().lower()
        if head.startswith(b"<") or b"<table" in head:
            return _html_tables(b.decode("utf-8", errors="ignore"))
        return pd.read_excel(io.BytesIO(b), engine="xlrd", header=None)
    return pd.read_excel(io.BytesIO(b), header=None)


def _html_tables(html: str) -> pd.DataFrame:
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return pd.DataFrame()
    best, score_best = None, -1
    for t in tables:
        if t.empty or t.shape[1] < 2:
            continue
        cols = " ".join(str(c).upper() for c in t.columns)
        score = sum(p for k, p in [("TRADING MEMBER", 5), ("TM", 2), ("NAME", 2),
                                   ("UCC", 4), ("CLIENT", 3), ("COMPLAINT", 4),
                                   ("ACTIVE", 2), ("RESOLVED", 3)] if k in cols)
        score += min(len(t) / 10, 10)
        if score > score_best:
            best, score_best = t, score
    if best is None:
        return pd.DataFrame()
    hdr = pd.DataFrame([list(best.columns)])
    body = best.copy()
    body.columns = range(len(body.columns))
    hdr.columns = range(len(hdr.columns))
    return pd.concat([hdr, body], ignore_index=True)


def detect_report_type(raw: pd.DataFrame, filename: str = "") -> str:
    fn = filename.upper()
    head = " ".join(str(v).upper() for i in range(min(6, len(raw)))
                    for v in raw.iloc[i].values if pd.notna(v))
    if "REPORT 1A" in head or ("1A" in fn and "DETAILS OF COMPLAINT" in head):
        return "1A"
    if "REPORT 3B" in head or "NAME OF ARBITRATOR" in head:
        return "3B"
    if "REPORT 4B" in head or "PENAL ACTION" in head:
        return "4B"
    if "REPORT 1C" in head or ("NAME OF THE TM" in head and "REDRESSAL" in head):
        return "1C"
    cols_txt = " ".join(str(c).upper() for c in raw.columns)
    if "STATE" in head + cols_txt and "UCC" in head + cols_txt:
        return "clients"
    first = str(raw.columns[0]).upper() if len(raw.columns) else ""
    if first in ("BROKER", "TM", "TRADING MEMBER", "TM_NAME", "NAME") and raw.shape[1] >= 3:
        num = sum(pd.to_numeric(raw[c], errors="coerce").notna().mean() > 0.7
                  for c in raw.columns[1:])
        if num >= 2:
            return "timeseries"
    if "NAME OF THE TM" in head:
        return "1C"
    return "unknown"


def detect_and_parse(raw):
    hdr_row = None
    for i, row in raw.iterrows():
        vals = " ".join(str(v).upper() for v in row.values if pd.notna(v))
        if "NAME OF THE TM" in vals or ("NAME" in vals and "TM" in vals):
            hdr_row = i
            break
    if hdr_row is None:
        return None, raw
    n = len(raw.columns)

    def row(off):
        idx = hdr_row + off
        return ([str(v).strip() if pd.notna(v) else "" for v in raw.iloc[idx]]
                if idx < len(raw) else [""] * n)

    r0, r1, r2 = row(0), row(1), row(2)
    has_sub = any(k in " ".join(r2).upper()
                  for k in ["RESOLVED", "PERCENTAGE", "PENDING", "ACTIONABLE"])
    start = hdr_row + (3 if has_sub else 2)
    cols = []
    for i in range(n):
        pick = (r2[i] if i < len(r2) and r2[i] else
                r1[i] if i < len(r1) and r1[i] else
                r0[i] if i < len(r0) and r0[i] else f"col_{i}")
        cols.append(pick)
    data = raw.iloc[start:].copy()
    data.columns = cols[:len(data.columns)]
    return cols, data.reset_index(drop=True)


def clean_df(data):
    seen, nc = {}, []
    for c in data.columns:
        if c in seen:
            seen[c] += 1
            nc.append(f"{c}_dup{seen[c]}")
        else:
            seen[c] = 0
            nc.append(c)
    data = data.copy()
    data.columns = nc
    cmap, mapped = {}, set()

    def m(s, t):
        if t not in mapped:
            cmap[s] = t
            mapped.add(t)

    for c in data.columns:
        cu = c.upper()
        if "NAME" in cu and "TM" in cu:                              m(c, "tm_name")
        elif "DEFAULT" in cu:                                        m(c, "defaulter")
        elif "UCC" in cu or ("ACTIVE" in cu and "CLIENT" in cu):     m(c, "active_clients")
        elif "NO. OF COMPLAINTS RECEIVED" in cu:                     m(c, "complaints_received")
        elif "COMPLAINTS" in cu and "RECEIVED" in cu and "AGAINST" not in cu:
            m(c, "complaints_received")
        elif "RESOLVED" in cu and ("EXCHANGE" in cu or "IGRC" in cu): m(c, "resolved")
        elif "NON ACTIONABLE" in cu:                                 m(c, "non_actionable")
        elif "ARBITRATION" in cu and "OPTED" in cu:                  m(c, "opted_arb")
        elif "PENDING" in cu and "EXCHANGE" in cu:                   m(c, "pending")
        elif "PERCENTAGE" in cu and "RESOLVED" in cu:                m(c, "pct_resolved")
        elif "ARBITRATION FILED" in cu:                              m(c, "arb_filed")
    df = data.rename(columns=cmap).copy()
    df = df.loc[:, ~df.columns.str.contains("_dup", na=False)]
    if "tm_name" in df.columns:
        df = df[df["tm_name"].notna()]
        df = df[~df["tm_name"].astype(str).str.upper().str.contains(
            r"GRAND TOTAL|^\s*TOTAL|\*|NOTE|ACTIVE CLIENT|PERCENTAGE",
            na=False, regex=True)]
        df = df[df["tm_name"].astype(str).str.strip().str.len() > 2]
    for col in ["active_clients", "complaints_received", "resolved",
                "non_actionable", "opted_arb", "pending", "pct_resolved",
                "arb_filed"]:
        if col not in df.columns:
            continue
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s = s.astype(str).str.strip().replace({"-": np.nan, "—": np.nan, "": np.nan})
        df[col] = pd.to_numeric(s, errors="coerce")
    if {"complaints_received", "resolved"} <= set(df.columns):
        if "pending" not in df.columns:
            df["pending"] = df["complaints_received"] - df["resolved"]
        if "pct_resolved" not in df.columns:
            df["pct_resolved"] = (df["resolved"] / df["complaints_received"] * 100).round(2)
    if {"complaints_received", "active_clients"} <= set(df.columns):
        df["density"] = (df["complaints_received"] / df["active_clients"] * 10000
                         ).replace([np.inf, -np.inf], np.nan)
    return df.reset_index(drop=True)


def parse_report_1a(raw):
    hdr = None
    for i in range(min(8, len(raw))):
        v = " ".join(str(x).upper() for x in raw.iloc[i].values if pd.notna(x))
        if "DATE OF RECEIPT" in v and "NAME OF TM" in v:
            hdr = i
            break
    if hdr is None:
        return pd.DataFrame()
    cols = [str(v).strip() if pd.notna(v) else f"col_{j}"
            for j, v in enumerate(raw.iloc[hdr])]
    df = raw.iloc[hdr + 1:].copy()
    df.columns = cols[:len(df.columns)]
    ren = {}
    for c in df.columns:
        cu = str(c).upper()
        if "DATE OF RECEIPT" in cu:      ren[c] = "date"
        elif "TYPE OF COMPLAINT" in cu:  ren[c] = "type"
        elif "NAME OF TM" in cu:         ren[c] = "tm_name"
        elif cu.startswith("STATUS**") or cu == "STATUS": ren[c] = "status"
        elif "STATUS DATE" in cu:        ren[c] = "status_date"
    df = df.rename(columns=ren)
    df = df[df["tm_name"].notna() & (df["tm_name"].astype(str).str.len() > 2)]
    df = df[~df["tm_name"].astype(str).str.upper().str.contains(
        "REPORT 1A|NAME OF TM", na=False)]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "status_date" in df.columns:
        df["status_date"] = pd.to_datetime(df["status_date"], errors="coerce")
        df["days_to_resolve"] = (df["status_date"] - df["date"]).dt.days
    return df.reset_index(drop=True)


def parse_report_4b(raw):
    hdr = None
    for i in range(min(6, len(raw))):
        v = " ".join(str(x).upper() for x in raw.iloc[i].values if pd.notna(x))
        if "NAME OF TRADING MEMBER" in v:
            hdr = i
            break
    if hdr is None:
        return pd.DataFrame()
    df = raw.iloc[hdr + 3:].copy()
    base = ["sn", "tm_name", "reg_no", "complaints", "penal_complaints",
            "penal_others", "penalty_complaints_lakh", "penalty_others_lakh",
            "arb_awards"]
    df = df.iloc[:, :len(base)]
    df.columns = base[:df.shape[1]]
    df = df[df["tm_name"].notna() & (df["tm_name"].astype(str).str.len() > 2)]
    df = df[~df["tm_name"].astype(str).str.upper().str.contains(
        "REPORT 4B|TRADING MEMBER|NOTE|TOTAL", na=False)]
    for c in base[3:]:
        if c in df.columns:
            s = df[c].astype(str).str.strip().replace({"-": np.nan, "": np.nan})
            df[c] = pd.to_numeric(s, errors="coerce")
    df["total_penalty_lakh"] = (df["penalty_complaints_lakh"].fillna(0)
                                + df["penalty_others_lakh"].fillna(0))
    return df.reset_index(drop=True)


def parse_report_3b(raw):
    hdr = None
    for i in range(min(6, len(raw))):
        v = " ".join(str(x).upper() for x in raw.iloc[i].values if pd.notna(x))
        if "NAME OF ARBITRATOR" in v:
            hdr = i
            break
    if hdr is None:
        return pd.DataFrame()
    df = raw.iloc[hdr + 2:].copy()
    base = ["sn", "arbitrator", "awards_arb", "awards_app", "fav_tm",
            "fav_cl", "app_fav_tm", "app_fav_cl", "pending"]
    df = df.iloc[:, :len(base)]
    df.columns = base[:df.shape[1]]
    df = df[df["arbitrator"].notna()]
    df = df[~df["arbitrator"].astype(str).str.upper().str.contains(
        "REPORT 3B|ARBITRATOR|NOTE", na=False)]
    for c in df.columns:
        if c != "arbitrator":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.reset_index(drop=True)


def parse_client_accounts(raw):
    df = raw.copy()
    if all(isinstance(c, int) for c in df.columns):
        df.columns = [str(v).strip() for v in df.iloc[0]]
        df = df.iloc[1:]
    ren = {}
    for c in df.columns:
        cu = str(c).upper()
        if "STATE" in cu:
            ren[c] = "state"
        elif "ALL UCC" in cu or "TILL" in cu:
            ren[c] = "total_ucc"
    df = df.rename(columns=ren)
    if "state" not in df.columns:
        df = df.rename(columns={df.columns[0]: "state"})
    for c in df.columns:
        if c != "state":
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""),
                                  errors="coerce")
    df = df[df["state"].notna()]
    df = df[~df["state"].astype(str).str.upper().str.contains("TOTAL", na=False)]
    return df.reset_index(drop=True)


def short(name, n=26):
    s = str(name).strip()
    return s[:n] + "…" if len(s) > n else s


def fmt_in(n):
    if pd.isna(n):
        return "—"
    n = float(n)
    if n >= 1e7:
        return f"{n/1e7:.2f} Cr"
    if n >= 1e5:
        return f"{n/1e5:.2f} L"
    return f"{n:,.0f}"


# ═══════════════════════════════════════════════════════════════════
# ANALYTICS → one JSON payload for the frontend
# ═══════════════════════════════════════════════════════════════════

def build_payload():
    periods, other = {}, {}
    files_seen = []

    if not REPORTS_DIR.exists():
        sys.exit(f"❌ {REPORTS_DIR} not found. Create it and add report files.")

    for p in sorted(REPORTS_DIR.iterdir()):
        if p.suffix.lower() not in {".csv", ".xls", ".xlsx", ".xlsm", ".html", ".htm"}:
            continue
        raw = load_raw(p)
        rt = detect_report_type(raw, p.name)
        files_seen.append((p.name, rt))
        if rt == "1A":
            other["1A"] = parse_report_1a(raw)
        elif rt == "3B":
            other["3B"] = parse_report_3b(raw)
        elif rt == "4B":
            other["4B"] = parse_report_4b(raw)
        elif rt == "clients":
            other["clients"] = parse_client_accounts(raw)
        elif rt == "timeseries":
            name_col = raw.columns[0]
            for c in raw.columns[1:]:
                vals = pd.to_numeric(raw[c], errors="coerce")
                if vals.notna().mean() < 0.5:
                    continue
                sub = pd.DataFrame({"tm_name": raw[name_col].astype(str),
                                    "active_clients": vals}).dropna()
                periods.setdefault("__ts__", {})[str(c)] = sub
        else:
            cols, parsed = detect_and_parse(raw)
            df = clean_df(parsed if cols else raw)
            if not df.empty and "tm_name" in df.columns:
                m = re.search(r"(\d{2})(\d{2})", p.name)
                label = f"FY {m.group(1)}–{m.group(2)}" if m else p.stem
                periods[label] = df

    ts_periods = periods.pop("__ts__", {})
    # Main period must be a 1C-style frame WITH complaints data
    main_label = next(
        (k for k, v in periods.items()
         if "complaints_received" in v.columns
         and v["complaints_received"].notna().any()), None)
    if main_label is None:
        sys.exit("❌ No Report 1C found in data/reports/ — the dashboard "
                 "needs at least one for the core analysis.")
    df = periods[main_label]
    dfa = df[df["complaints_received"].notna()
             & (df["complaints_received"] > 0)].copy()
    dfa["tm_short"] = dfa["tm_name"].apply(short)

    tot_c = int(dfa["complaints_received"].sum())
    tot_r = int(dfa["resolved"].sum())
    tot_p = int(dfa["pending"].sum())
    rate = tot_r / tot_c * 100 if tot_c else 0
    n_tm = len(dfa)
    med = float(dfa["pct_resolved"].median())
    n_def = int(dfa["defaulter"].astype(str).str.upper()
                .str.contains("YES").sum()) if "defaulter" in dfa else 0

    health = ("CRITICAL" if rate < 50 else "NEEDS ATTENTION" if rate < 65
              else "BELOW TARGET" if rate < 80 else "HEALTHY")

    # Pareto
    par = dfa.sort_values("complaints_received", ascending=False).head(25)
    cum = (par["complaints_received"].cumsum() / tot_c * 100).round(1)
    n80 = int((dfa.sort_values("complaints_received", ascending=False)
               ["complaints_received"].cumsum() / tot_c * 100 <= 80).sum()) + 1

    # Leaderboards
    hv = dfa[dfa["complaints_received"] >= 20]
    best5 = hv.nlargest(5, "pct_resolved")
    worst5 = hv.nsmallest(5, "pct_resolved")
    vol5 = dfa.nlargest(5, "complaints_received")
    pend5 = dfa.nlargest(5, "pending")

    # Quadrant
    med_vol = float(dfa["complaints_received"].median())
    quad = dfa.dropna(subset=["pct_resolved"]).copy()
    quad["seg"] = quad.apply(
        lambda r: ("priority" if r["complaints_received"] >= med_vol
                   and r["pct_resolved"] < TARGET_RATE else
                   "leader" if r["complaints_received"] >= med_vol else
                   "watch" if r["pct_resolved"] < TARGET_RATE else "healthy"),
        axis=1)

    # Concentration
    ms = dfa[dfa["active_clients"].fillna(0) > 0]
    tot_ac = float(ms["active_clients"].sum())
    ms = ms.assign(share=ms["active_clients"] / tot_ac * 100).sort_values(
        "active_clients", ascending=False)
    hhi = int((ms["share"] ** 2).sum())
    cr3 = float(ms["share"].head(3).sum())
    cr10 = float(ms["share"].head(10).sum())
    top10_ms = ms.head(10)

    # Findings
    findings = []
    findings.append(("neutral", f"<b>Complaint concentration:</b> {n80} of "
                     f"{n_tm} brokers ({n80/n_tm*100:.0f}%) generate 80% of all "
                     f"complaints. Largest source: <b>{vol5.iloc[0]['tm_short']}"
                     f"</b> with {int(vol5.iloc[0]['complaints_received'])} "
                     f"({vol5.iloc[0]['complaints_received']/tot_c*100:.1f}% of market)."))
    if not best5.empty and not worst5.empty:
        gap = best5.iloc[0]["pct_resolved"] - worst5.iloc[0]["pct_resolved"]
        findings.append(("warning", f"<b>Performance gap:</b> resolution rates "
                         f"span {worst5.iloc[0]['pct_resolved']:.1f}% "
                         f"(<b>{worst5.iloc[0]['tm_short']}</b>) to "
                         f"{best5.iloc[0]['pct_resolved']:.1f}% "
                         f"(<b>{best5.iloc[0]['tm_short']}</b>) — a "
                         f"{gap:.0f}-point spread among meaningful-volume brokers."))
    big4 = dfa[dfa["tm_name"].str.contains("Groww|Zerodha|Angel|Upstox",
                                           case=False, na=False)]
    if len(big4) >= 3:
        b4c = int(big4["complaints_received"].sum())
        b4r = b4c and int(big4["resolved"].sum()) / b4c * 100
        findings.append(("neutral", f"<b>Discount-broker cohort:</b> Groww, "
                         f"Zerodha, Angel One & Upstox received <b>{b4c:,} "
                         f"complaints ({b4c/tot_c*100:.0f}% of market)</b>, "
                         f"resolving {b4r:.1f}% — "
                         f"{'above' if b4r > rate else 'below'} the market "
                         f"average of {rate:.1f}%."))
    if n_def:
        dn = dfa[dfa["defaulter"].astype(str).str.upper()
                 .str.contains("YES")]["tm_name"]
        findings.append(("risk", f"<b>Defaulter alert:</b> {n_def} TM(s) "
                         f"flagged: <b>{', '.join(dn.head(3))}</b>."))
    arb = int(dfa["arb_filed"].sum()) if "arb_filed" in dfa else 0
    if arb == 0:
        findings.append(("neutral", "<b>Escalation channel unused:</b> zero "
                         "arbitration filings despite "
                         f"{tot_p:,} pending complaints — disputes settle at "
                         "exchange/IGRC level, or investors are not escalating."))

    payload = {
        "generated": datetime.now().strftime("%d %b %Y, %H:%M"),
        "period": main_label,
        "files": [{"name": n, "type": t} for n, t in files_seen],
        "kpi": {"tms": n_tm, "complaints": tot_c, "resolved": tot_r,
                "pending": tot_p, "rate": round(rate, 1),
                "median": round(med, 1), "defaulters": n_def,
                "gap": round(rate - TARGET_RATE, 1), "health": health,
                "active_clients": fmt_in(tot_ac)},
        "pareto": {"names": par["tm_short"].tolist(),
                   "complaints": par["complaints_received"].astype(int).tolist(),
                   "cum": cum.tolist(), "n80": n80},
        "stack10": {"names": vol5["tm_short"].tolist() +
                    dfa.nlargest(10, "complaints_received")
                    .iloc[5:]["tm_short"].tolist(),
                    "resolved": dfa.nlargest(10, "complaints_received")
                    ["resolved"].fillna(0).astype(int).tolist(),
                    "pending": dfa.nlargest(10, "complaints_received")
                    ["pending"].fillna(0).astype(int).tolist(),
                    "rate": dfa.nlargest(10, "complaints_received")
                    ["pct_resolved"].round(1).tolist(),
                    "labels": dfa.nlargest(10, "complaints_received")
                    ["tm_short"].tolist()},
        "boards": {
            "best": [[r.tm_short, round(r.pct_resolved, 1),
                      int(r.complaints_received)] for r in best5.itertuples()],
            "worst": [[r.tm_short, round(r.pct_resolved, 1),
                       int(r.complaints_received)] for r in worst5.itertuples()],
            "volume": [[r.tm_short, int(r.complaints_received),
                        round(r.pct_resolved, 1) if pd.notna(r.pct_resolved)
                        else None] for r in vol5.itertuples()],
            "pending": [[r.tm_short, int(r.pending),
                         round(r.pending / r.complaints_received * 100)]
                        for r in pend5.itertuples()],
        },
        "quadrant": {"x": quad["complaints_received"].astype(int).tolist(),
                     "y": quad["pct_resolved"].round(1).tolist(),
                     "names": quad["tm_short"].tolist(),
                     "seg": quad["seg"].tolist(),
                     "size": quad["active_clients"].fillna(
                         quad["active_clients"].median()).tolist(),
                     "med_vol": med_vol},
        "conc": {"hhi": hhi, "cr3": round(cr3, 1), "cr10": round(cr10, 1),
                 "hhi_label": ("Highly concentrated" if hhi > 2500 else
                               "Moderately concentrated" if hhi > 1500
                               else "Competitive"),
                 "names": top10_ms["tm_short"].tolist(),
                 "share": top10_ms["share"].round(2).tolist(),
                 "clients": [fmt_in(v) for v in top10_ms["active_clients"]],
                 "others": round(100 - top10_ms["share"].sum(), 1)},
        "findings": [{"k": k, "t": t} for k, t in findings],
        "table": [[r.tm_name,
                   str(getattr(r, "defaulter", "")),
                   fmt_in(getattr(r, "active_clients", np.nan)),
                   int(r.complaints_received),
                   int(r.resolved) if pd.notna(r.resolved) else 0,
                   int(r.pending) if pd.notna(r.pending) else 0,
                   round(r.pct_resolved, 1) if pd.notna(r.pct_resolved) else None]
                  for r in dfa.sort_values("complaints_received",
                                           ascending=False).itertuples()],
        "other": {},
    }

    # Other reports
    if "1A" in other and not other["1A"].empty:
        d = other["1A"]
        types = d["type"].value_counts()
        daily = d.groupby(d["date"].dt.strftime("%d %b")).size()
        dd = d["days_to_resolve"].dropna()
        dd = dd[dd.between(0, 200)]
        hist_counts, hist_edges = np.histogram(dd, bins=24)
        payload["other"]["r1a"] = {
            "total": len(d),
            "resolved": int(d["status"].astype(str)
                            .str.contains("Resolved", case=False).sum()),
            "median_days": float(d["days_to_resolve"].median()),
            "p90_days": float(d["days_to_resolve"].quantile(.9)),
            "types": {"labels": types.index.tolist(),
                      "counts": types.values.tolist()},
            "daily": {"labels": daily.index.tolist(),
                      "counts": daily.values.tolist()},
            "hist": {"edges": hist_edges[:-1].round(0).tolist(),
                     "counts": hist_counts.tolist()},
        }
    if "4B" in other and not other["4B"].empty:
        d = other["4B"]
        top = d.nlargest(10, "total_penalty_lakh")
        payload["other"]["r4b"] = {
            "total_penalty": round(float(d["total_penalty_lakh"].sum()), 1),
            "tms_penalized": int((d["total_penalty_lakh"] > 0).sum()),
            "names": [short(x) for x in top["tm_name"]],
            "amounts": top["total_penalty_lakh"].round(2).tolist(),
        }
    if "3B" in other and not other["3B"].empty:
        d = other["3B"]
        payload["other"]["r3b"] = {
            "arbitrators": len(d),
            "awards": int(d[["awards_arb", "awards_app"]].sum().sum()),
        }
    if "clients" in other and not other["clients"].empty:
        d = other["clients"].nlargest(12, "total_ucc")
        allucc = float(other["clients"]["total_ucc"].sum())
        payload["other"]["clients"] = {
            "total": fmt_in(allucc),
            "states": d["state"].astype(str).str.title().tolist(),
            "ucc": d["total_ucc"].astype(float).tolist(),
            "top_share": round(float(d["total_ucc"].head(5).sum())
                               / allucc * 100, 1),
        }

    return payload


# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ═══════════════════════════════════════════════════════════════════

def render(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    template = Path(__file__).parent / "template.html"
    html = template.read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", data_json)

    # Inline Plotly if a local bundle exists → page works fully offline
    plotly_local = Path(__file__).parent / "assets" / "plotly.min.js"
    cdn_tag = '<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>'
    if plotly_local.exists():
        js = plotly_local.read_text(encoding="utf-8")
        html = html.replace(cdn_tag, "<script>" + js + "</script>")
    return html


if __name__ == "__main__":
    print("📡 Broker's Pulse generator")
    print(f"   Scanning {REPORTS_DIR} …")
    payload = build_payload()
    for f in payload["files"]:
        print(f"   ✅ {f['name']}  →  {f['type']}")
    OUTPUT.write_text(render(payload), encoding="utf-8")
    print(f"   📝 Wrote {OUTPUT}  ({OUTPUT.stat().st_size/1024:.0f} KB)")
    print("   Open index.html in a browser, or host it anywhere.")
