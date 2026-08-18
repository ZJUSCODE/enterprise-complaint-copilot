from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.domain import classify_category, classify_complaint, contains_any
from app.utils import clamp, summarize_text


class LocalAnalyticsEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.frames = self._load_frames()
        self.dataset = self._build_dataset()
        self.user_summary = self._build_user_summary()

    def _load_csv(self, name: str) -> pd.DataFrame:
        return pd.read_csv(self.data_dir / name)

    def _load_frames(self) -> dict[str, pd.DataFrame]:
        return {
            "orders": self._load_csv("olist_orders_dataset.csv"),
            "order_items": self._load_csv("olist_order_items_dataset.csv"),
            "reviews": self._load_csv("olist_order_reviews_dataset.csv"),
            "products": self._load_csv("olist_products_dataset.csv"),
        }

    def _build_dataset(self) -> pd.DataFrame:
        orders = self.frames["orders"].copy()
        items = self.frames["order_items"].copy()
        reviews = self.frames["reviews"].copy()
        products = self.frames["products"].copy()

        orders["order_purchase_timestamp"] = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
        reviews["review_comment_message"] = reviews["review_comment_message"].fillna("")
        products["macro_category"] = products["product_category_name"].fillna("").map(classify_category)

        review_rank = reviews.assign(comment_len=reviews["review_comment_message"].str.len())
        review_rank = review_rank.sort_values(["review_score", "comment_len"], ascending=[True, False]).drop_duplicates("order_id")

        merged = orders.merge(items, on="order_id", how="left")
        merged = merged.merge(review_rank[["order_id", "review_score", "review_comment_message"]], on="order_id", how="left")
        merged = merged.merge(products[["product_id", "product_category_name", "macro_category"]], on="product_id", how="left")

        merged["review_score"] = merged["review_score"].fillna(5)
        merged["review_comment_message"] = merged["review_comment_message"].fillna("")
        merged["macro_category"] = merged["macro_category"].fillna("其他")
        merged["complaint_type"] = merged.apply(lambda row: classify_complaint(row["review_comment_message"], row["review_score"]), axis=1)
        merged["is_bad_review"] = (merged["review_score"] <= 2).astype(int)
        merged["compensation_amount"] = (merged["price"].fillna(0) * merged["is_bad_review"] * 0.35 + merged["freight_value"].fillna(0) * merged["is_bad_review"]).round(2)
        merged["user_id"] = merged["customer_id"]
        return merged

    def _build_user_summary(self) -> pd.DataFrame:
        grouped = self.dataset.groupby("user_id", dropna=False).agg(
            total_spend=("price", "sum"),
            avg_price=("price", "mean"),
            avg_freight=("freight_value", "mean"),
            order_count=("order_id", "nunique"),
            bad_review_count=("is_bad_review", "sum"),
            compensation_total=("compensation_amount", "sum"),
        ).reset_index()
        grouped["risk_score"] = grouped.apply(self._score_user_row, axis=1).round(4)
        grouped["risk_level"] = grouped["risk_score"].map(lambda value: "高风险" if value >= 0.62 else "观察中" if value >= 0.4 else "正常")
        grouped["suggestion"] = grouped["risk_level"].map({"高风险": "建议主管介入，限制直接扩赔", "观察中": "建议关注最近工单，必要时人工复核", "正常": "可按标准流程继续处理"})
        return grouped

    def _score_user_row(self, row: pd.Series) -> float:
        spend_factor = min((row["total_spend"] or 0) / 600.0, 1.0)
        complaint_factor = min((row["bad_review_count"] or 0) / 2.0, 1.0)
        frequency_factor = min((row["order_count"] or 0) / 5.0, 1.0)
        compensation_factor = min((row["compensation_total"] or 0) / 200.0, 1.0)
        return clamp(0.18 * spend_factor + 0.42 * complaint_factor + 0.16 * frequency_factor + 0.24 * compensation_factor, 0.02, 0.98)

    def _daily_order_counts(self) -> tuple[pd.DataFrame, pd.Timestamp | None]:
        dated_df = self.dataset.dropna(subset=["order_purchase_timestamp"]).copy()
        if dated_df.empty:
            return pd.DataFrame(columns=["bad", "total"]), None
        dated_df["trend_date"] = dated_df["order_purchase_timestamp"].dt.normalize()
        dated_df["bad_order_id"] = dated_df["order_id"].where(dated_df["is_bad_review"] == 1)
        daily = dated_df.groupby("trend_date").agg(
            bad=("bad_order_id", "nunique"),
            total=("order_id", "nunique"),
        )
        latest_day = dated_df["trend_date"].max()
        calendar = pd.date_range(start=daily.index.min(), end=latest_day, freq="D")
        return daily.reindex(calendar, fill_value=0), latest_day

    @staticmethod
    def _select_complete_window(daily: pd.DataFrame, days: int = 30) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        if daily.empty:
            return None, None
        fallback_end = daily.index[-1]
        for window_end in reversed(daily.index[days - 1:]):
            window_start = window_end - pd.Timedelta(days=days - 1)
            window = daily.loc[window_start:window_end]
            median_orders = max(float(window["total"].median()), 1.0)
            if len(window) == days and float(window["total"].min()) >= median_orders * 0.2:
                return window_start, window_end
        return fallback_end - pd.Timedelta(days=days - 1), fallback_end

    def get_overview(self) -> dict[str, Any]:
        high_risk = self.user_summary[self.user_summary["risk_level"] == "高风险"]
        daily, latest_day = self._daily_order_counts()
        trend_start, trend_end = self._select_complete_window(daily)
        trend: list[dict[str, Any]] = []
        if trend_start is not None and trend_end is not None:
            trend_df = daily.loc[trend_start:trend_end]
            trend = [
                {"date": day.strftime("%Y-%m-%d"), "bad": int(row["bad"]), "total": int(row["total"])}
                for day, row in trend_df.iterrows()
            ]

        token_counter: dict[str, int] = {}
        stopwords = {"para", "com", "que", "não", "nao", "foi", "uma", "produto", "muito", "mais", "sem", "isso", "the", "and"}
        for comment in self.dataset.loc[self.dataset["is_bad_review"] == 1, "review_comment_message"].astype(str):
            for token in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", comment.lower()):
                if token not in stopwords:
                    token_counter[token] = token_counter.get(token, 0) + 1
        top_keywords = [{"word": word, "count": count} for word, count in sorted(token_counter.items(), key=lambda item: item[1], reverse=True)[:8]]

        complaint_mix_df = self.dataset[self.dataset["is_bad_review"] == 1].groupby("complaint_type").agg(count=("order_id", "nunique")).reset_index().sort_values("count", ascending=False)
        return {
            "risk_rate": round(len(high_risk) / max(len(self.user_summary), 1), 4),
            "high_risk_cnt": int(len(high_risk)),
            "total_users": int(len(self.user_summary)),
            "trend": trend,
            "top_keywords": top_keywords,
            "complaint_mix": [{"label": row["complaint_type"], "value": int(row["count"])} for _, row in complaint_mix_df.iterrows()],
            "latest_snapshot": latest_day.strftime("%Y-%m-%d") if latest_day is not None else "无数据",
            "trend_window_start": trend_start.strftime("%Y-%m-%d") if trend_start is not None else None,
            "trend_window_end": trend_end.strftime("%Y-%m-%d") if trend_end is not None else None,
        }

    def get_daily_risk_report(self, report_date: str | None = None) -> dict[str, Any]:
        df = self.dataset.dropna(subset=["order_purchase_timestamp"]).copy()
        if df.empty:
            return {
                "report_id": "RPT-empty",
                "report_date": report_date,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "headline": "当前没有可生成日报的数据。",
                "metrics": [],
                "top_risks": [],
                "recommended_actions": ["确认合成演示数据是否已生成。"],
                "delivery_mock": {"channel": "Feishu/WeCom", "status": "mock_not_sent"},
                "markdown": "当前没有可生成日报的数据。",
            }

        df["report_date"] = df["order_purchase_timestamp"].dt.strftime("%Y-%m-%d")
        _, trend_end = self._select_complete_window(self._daily_order_counts()[0])
        normalized_date = report_date or (trend_end.strftime("%Y-%m-%d") if trend_end is not None else str(df["report_date"].max()))
        day_df = df[df["report_date"] == normalized_date]
        if day_df.empty:
            normalized_date = str(df["report_date"].max())
            day_df = df[df["report_date"] == normalized_date]

        bad_df = day_df[day_df["is_bad_review"] == 1].copy()
        total_orders = int(day_df["order_id"].nunique())
        abnormal_orders = int(bad_df["order_id"].nunique())
        compensation_total = round(float(bad_df["compensation_amount"].fillna(0).sum()), 2)
        abnormal_rate = round((abnormal_orders / total_orders) * 100, 1) if total_orders else 0.0

        top_risks: list[dict[str, Any]] = []
        if not bad_df.empty:
            grouped = (
                bad_df.groupby(["macro_category", "complaint_type"], dropna=False)
                .agg(order_count=("order_id", "nunique"), compensation_total=("compensation_amount", "sum"))
                .reset_index()
                .sort_values(["compensation_total", "order_count"], ascending=False)
                .head(5)
            )
            for _, row in grouped.iterrows():
                count = int(row["order_count"] or 0)
                top_risks.append({
                    "category": row["macro_category"] or "其他",
                    "complaint_type": row["complaint_type"] or "一般咨询",
                    "order_count": count,
                    "compensation_total": round(float(row["compensation_total"] or 0), 2),
                    "share": round((count / abnormal_orders) * 100, 1) if abnormal_orders else 0,
                    "reason": "低分评价或客诉文本命中异常规则。",
                })

        top_cases = []
        if not bad_df.empty:
            case_df = bad_df.sort_values("compensation_amount", ascending=False).drop_duplicates("order_id").head(5)
            for _, row in case_df.iterrows():
                top_cases.append({
                    "order_id": row["order_id"],
                    "user_id": row["user_id"],
                    "category": row["macro_category"],
                    "complaint_type": row["complaint_type"],
                    "compensation_amount": round(float(row["compensation_amount"] or 0), 2),
                    "comment": summarize_text(row["review_comment_message"] or "-", limit=90),
                })

        recommended_actions = [
            "主管优先查看高赔付异常工单。",
            "运营按类目复盘异常原因，并准备客服安抚口径。",
        ]
        if abnormal_orders == 0:
            recommended_actions = ["当日未命中异常评价，维持常规监控。"]
        elif compensation_total >= 500:
            recommended_actions.insert(0, "赔付金额较高，建议当天完成人工复核。")

        headline = f"{normalized_date} 异常播报：{abnormal_orders} 单异常，占比 {abnormal_rate}%，估算赔付 ¥{compensation_total:.2f}。"
        markdown_lines = [
            f"# 每日异常播报 {normalized_date}",
            "",
            f"- 总订单量：{total_orders}",
            f"- 异常工单：{abnormal_orders}",
            f"- 异常占比：{abnormal_rate}%",
            f"- 估算赔付：¥{compensation_total:.2f}",
            "",
            "## Top 风险",
        ]
        if top_risks:
            markdown_lines.extend(
                f"- {item['category']} / {item['complaint_type']}：{item['order_count']} 单，赔付 ¥{item['compensation_total']:.2f}，占比 {item['share']}%"
                for item in top_risks
            )
        else:
            markdown_lines.append("- 当日未命中异常风险。")
        markdown_lines.extend(["", "## 建议动作", *[f"- {item}" for item in recommended_actions]])

        return {
            "report_id": f"RPT-{normalized_date.replace('-', '')}",
            "report_date": normalized_date,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "headline": headline,
            "metrics": [
                {"label": "总订单量", "value": total_orders},
                {"label": "异常工单", "value": abnormal_orders},
                {"label": "异常占比", "value": f"{abnormal_rate}%"},
                {"label": "估算赔付", "value": round(compensation_total, 2)},
            ],
            "top_risks": top_risks,
            "top_cases": top_cases,
            "recommended_actions": recommended_actions,
            "delivery_mock": {
                "channel": "Feishu/WeCom",
                "status": "mock_not_sent",
                "schedule": "daily 09:30",
                "note": "当前只生成可发送内容，不调用真实 webhook。",
            },
            "markdown": "\n".join(markdown_lines),
        }

    def _order_row(self, order_id: str) -> pd.Series | None:
        rows = self.dataset[self.dataset["order_id"] == order_id]
        if rows.empty:
            return None
        return rows.iloc[0]

    def query_order_status(self, order_id: str) -> dict[str, Any]:
        row = self._order_row(order_id)
        if row is None:
            return {"found": False, "order_id": order_id, "error_code": "order_not_found"}
        return {
            "found": True,
            "order_id": order_id,
            "user_id": str(row.get("user_id", "")),
            "order_status": str(row.get("order_status", "unknown")),
            "category": str(row.get("macro_category", "unknown")),
            "created_at": str(row.get("order_purchase_timestamp", "")),
            "approved_at": str(row.get("order_approved_at", "")),
            "estimated_delivery_at": str(row.get("order_estimated_delivery_date", "")),
            "review_score": int(row.get("review_score", 0) or 0),
        }

    def query_logistics_status(self, order_id: str) -> dict[str, Any]:
        row = self._order_row(order_id)
        if row is None:
            return {"found": False, "order_id": order_id, "error_code": "order_not_found"}
        delivered = pd.to_datetime(row.get("order_delivered_customer_date"), errors="coerce")
        estimated = pd.to_datetime(row.get("order_estimated_delivery_date"), errors="coerce")
        delayed_days = 0
        if pd.notna(delivered) and pd.notna(estimated):
            delayed_days = max((delivered - estimated).days, 0)
        status = "delayed" if delayed_days > 0 else str(row.get("order_status", "unknown"))
        return {
            "found": True,
            "order_id": order_id,
            "logistics_status": status,
            "delivered_at": str(row.get("order_delivered_customer_date", "")),
            "estimated_delivery_at": str(row.get("order_estimated_delivery_date", "")),
            "delayed_days": delayed_days,
            "freight_value": round(float(row.get("freight_value", 0) or 0), 2),
        }

    def query_refund_eligibility(self, order_id: str, reason: str | None = None) -> dict[str, Any]:
        row = self._order_row(order_id)
        if row is None:
            return {"found": False, "order_id": order_id, "eligible": False, "error_code": "order_not_found"}
        complaint_type = str(row.get("complaint_type", ""))
        compensation = round(float(row.get("compensation_amount", 0) or 0), 2)
        review_score = int(row.get("review_score", 5) or 5)
        eligible = bool(review_score <= 2 or compensation > 0 or contains_any(reason or "", ["refund", "return", "damaged", "delay"]))
        priority = "high" if compensation >= 100 or review_score <= 1 else "medium" if eligible else "low"
        return {
            "found": True,
            "order_id": order_id,
            "eligible": eligible,
            "priority": priority,
            "complaint_type": complaint_type,
            "estimated_refund_amount": compensation,
            "reason": reason or complaint_type,
            "recommended_action": "escalate_to_supervisor" if priority == "high" else "standard_refund_review" if eligible else "collect_more_evidence",
        }

    def query_policy_by_market(self, market: str, topic: str) -> dict[str, Any]:
        market_code = market.strip().upper()
        baseline = {
            "BR": "Follow marketplace refund SLA, keep Portuguese customer evidence, and verify logistics timestamps before compensation.",
            "US": "Check return window, state-specific consumer protection notes, and payment dispute risk before final approval.",
            "EU": "Check withdrawal rights, warranty evidence, GDPR-safe notes, and seller response SLA.",
            "CN": "Check seven-day no-reason rules, platform category exceptions, invoice evidence, and escalation threshold.",
        }
        return {
            "market": market_code,
            "topic": topic,
            "policy": baseline.get(market_code, "Use global baseline policy and route market-specific uncertainty to supervisor review."),
            "requires_supervisor": market_code not in baseline or contains_any(topic, ["high value", "fraud", "cross-border", "跨境", "欺诈", "高额"]),
        }

    def get_user_risk(self, user_id: str) -> dict[str, Any]:
        row = self.user_summary[self.user_summary["user_id"] == user_id]
        if row.empty:
            return {"found": False, "message": f"未找到用户 {user_id} 的本地样本记录。"}
        item = row.iloc[0].to_dict()
        return {
            "found": True,
            "user_id": item["user_id"],
            "risk_score": round(float(item["risk_score"]), 4),
            "risk_level": item["risk_level"],
            "suggestion": item["suggestion"],
            "metrics": {"订单数": int(item["order_count"]), "差评触发数": int(item["bad_review_count"]), "累计实付": round(float(item["total_spend"]), 2), "累计赔付估算": round(float(item["compensation_total"]), 2)},
        }
