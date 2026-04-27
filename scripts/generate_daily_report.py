from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a mock daily abnormal-risk broadcast.")
    parser.add_argument("--date", default=None, help="Report date in YYYY-MM-DD. Defaults to the latest sample date.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args()


def main_cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = main.get_runtime().analytics.get_daily_risk_report(report_date=args.date)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["markdown"])


if __name__ == "__main__":
    main_cli()
