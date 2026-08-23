"""결정론적 계산 모듈 단위 테스트 — 네트워크를 타지 않는다.

실행: python3 -m unittest discover -s scripts/tests -t scripts
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dart
import dcf
import fmt
import render
import report_html
import indicators as ind
import metrics as met
import score
import validate


class TestIndicators(unittest.TestCase):
    def test_sma_pads_and_averages(self):
        self.assertEqual(ind.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_rsi_extremes(self):
        up = [float(i) for i in range(1, 40)]
        self.assertEqual(ind.rsi(up)[-1], 100.0)
        self.assertEqual(ind.rsi(list(reversed(up)))[-1], 0.0)

    def test_rsi_needs_history(self):
        self.assertTrue(all(v is None for v in ind.rsi([1.0, 2.0, 3.0])))

    def test_ema_matches_hand_calc(self):
        # 1..10, period 5 → 시드 SMA(1..5)=3, 이후 k=1/3로 평활 → 8.0
        self.assertAlmostEqual(ind.ema([float(i) for i in range(1, 11)], 5)[-1], 8.0, places=6)

    def test_trend_classification(self):
        self.assertEqual(ind.classify_trend(110, 105, 100, 90), "strong_uptrend")
        self.assertEqual(ind.classify_trend(80, 85, 90, 100), "strong_downtrend")
        # 200일선 위 + 정배열이지만 20일선 아래로 눌린 상태 → strong이 아닌 uptrend
        self.assertEqual(ind.classify_trend(95, 96, 93, 90), "uptrend")
        # MA가 뒤섞이면 추세로 보지 않는다
        self.assertEqual(ind.classify_trend(95, 90, 100, 92), "sideways")
        self.assertEqual(ind.classify_trend(100, None, None, None), "unknown")

    def test_analyze_rejects_short_series(self):
        bars = [{"date": "2026-01-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}] * 5
        self.assertFalse(ind.analyze(bars)["ok"])

    def test_bollinger_bands_bracket_middle(self):
        vals = [10.0, 11, 12, 11, 10, 9, 10, 11, 12, 13, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13]
        bb = ind.bollinger(vals, 20)
        self.assertLess(bb["lower"][-1], bb["middle"][-1])
        self.assertGreater(bb["upper"][-1], bb["middle"][-1])


class TestMetrics(unittest.TestCase):
    """가장 중요한 회귀 테스트: 회계연도가 어긋난 값끼리 나누면 안 된다."""

    def _facts(self):
        return {"facts": {"us-gaap": {
            # 기업이 중간에 태그를 바꾼 상황을 재현한다 — 옛 태그에 오래된 값만 남아 있다
            "Revenues": {"units": {"USD": [
                {"start": "2023-01-01", "end": "2023-12-31", "val": 100, "form": "10-K", "filed": "2024-02-01"},
                {"start": "2024-01-01", "end": "2024-12-31", "val": 150, "form": "10-K", "filed": "2025-02-01"},
                {"start": "2025-01-01", "end": "2025-12-31", "val": 200, "form": "10-K", "filed": "2026-02-01"},
            ]}},
            "SalesRevenueNet": {"units": {"USD": [
                {"start": "2019-01-01", "end": "2019-12-31", "val": 50, "form": "10-K", "filed": "2020-02-01"},
            ]}},
            "GrossProfit": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 120, "form": "10-K", "filed": "2026-02-01"},
            ]}},
            "OperatingIncomeLoss": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 80, "form": "10-K", "filed": "2026-02-01"},
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 60, "form": "10-K", "filed": "2026-02-01"},
            ]}},
            "StockholdersEquity": {"units": {"USD": [
                {"end": "2025-12-31", "val": 300, "form": "10-K", "filed": "2026-02-01"},
            ]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 90, "form": "10-K", "filed": "2026-02-01"},
            ]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 20, "form": "10-K", "filed": "2026-02-01"},
            ]}},
        }}}

    def test_picks_freshest_tag_not_first(self):
        st = met.extract_statements(self._facts())
        self.assertEqual(st["tagsUsed"]["revenue"], "Revenues")
        self.assertEqual(st["annual"]["revenue"][-1]["end"], "2025-12-31")

    def test_margins_use_same_fiscal_year(self):
        m = met.compute_metrics(met.extract_statements(self._facts()))
        self.assertAlmostEqual(m["profitability"]["grossMargin"], 0.6)
        self.assertAlmostEqual(m["profitability"]["operatingMargin"], 0.4)
        self.assertAlmostEqual(m["profitability"]["netMargin"], 0.3)
        self.assertAlmostEqual(m["profitability"]["roe"], 0.2)

    def test_growth_and_fcf(self):
        m = met.compute_metrics(met.extract_statements(self._facts()))
        self.assertAlmostEqual(m["growth"]["revenueYoY"], 200 / 150 - 1)
        self.assertAlmostEqual(m["cashFlow"]["freeCashFlow"], 70)

    def test_missing_is_not_zero(self):
        m = met.compute_metrics(met.extract_statements(self._facts()))
        self.assertIn("shortTermInvestments", m["dataGaps"])

    def test_duplicate_restatement_keeps_latest_filing(self):
        facts = self._facts()
        facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
            {"start": "2025-01-01", "end": "2025-12-31", "val": 205, "form": "10-K", "filed": "2026-06-01"})
        st = met.extract_statements(facts)
        self.assertEqual(st["annual"]["revenue"][-1]["value"], 205)

    def test_coverage_reports_missing_core_fields(self):
        cov = met._coverage({"annual": {"revenue": [{"end": "2025-12-31", "value": 1}]}})
        self.assertEqual(cov["ratio"], 0.2)
        self.assertIn("netIncome", cov["missing"])


class TestDart(unittest.TestCase):
    """한국(DART) 정규화 — 네트워크 없이 응답 모양만 검증한다."""

    def _rows(self):
        return [
            # 정상 BS 자본총계
            {"sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계",
             "thstrm_amount": "436320337000000", "frmtrm_amount": "402192143000000",
             "bfefrmtrm_amount": "363677865000000"},
            # SCE는 같은 account_id로 구성요소를 다시 내보낸다 — 반드시 무시해야 한다
            {"sj_div": "SCE", "account_id": "ifrs-full_Equity", "account_nm": "자본총계",
             "thstrm_amount": "4400000000000", "frmtrm_amount": "4400000000000",
             "bfefrmtrm_amount": "4400000000000"},
            # 손익계산서의 당기순이익
            {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익",
             "thstrm_amount": "45206805000000", "frmtrm_amount": "34451351000000",
             "bfefrmtrm_amount": "15487100000000"},
            # 현금흐름표에도 당기순이익이 나오지만 IS가 우선이다
            {"sj_div": "CF", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익",
             "thstrm_amount": "999", "frmtrm_amount": "999", "bfefrmtrm_amount": "999"},
            {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
             "account_nm": "지배기업 소유주지분", "thstrm_amount": "44260956000000",
             "frmtrm_amount": "33600000000000", "bfefrmtrm_amount": "14500000000000"},
            {"sj_div": "BS", "account_id": "ifrs-full_EquityAttributableToOwnersOfParent",
             "account_nm": "지배기업 소유주지분", "thstrm_amount": "424313255000000",
             "frmtrm_amount": "391700000000000", "bfefrmtrm_amount": "353200000000000"},
            {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
             "thstrm_amount": "333605938000000", "frmtrm_amount": "300870903000000",
             "bfefrmtrm_amount": "258935494000000"},
            # 차입금은 표준 ID가 없어 계정명으로 잡는다
            {"sj_div": "BS", "account_id": "-표준계정코드 미사용-", "account_nm": "단기차입금",
             "thstrm_amount": "1200000000000", "frmtrm_amount": "2200000000000",
             "bfefrmtrm_amount": "1300000000000"},
        ]

    def _ingest(self):
        collected, tags = {}, {}
        dart.ingest_rows(self._rows(), 2025, 12, collected, tags)
        return collected, tags

    def test_sce_rows_never_override_balance_sheet(self):
        """자본변동표가 자본총계를 4.4조로 덮어쓰던 실제 버그의 회귀 테스트."""
        collected, _ = self._ingest()
        self.assertEqual(collected["equity"]["2025-12-31"][1], 436320337000000.0)

    def test_income_statement_wins_over_cash_flow(self):
        collected, _ = self._ingest()
        self.assertEqual(collected["netIncome"]["2025-12-31"][1], 45206805000000.0)

    def test_one_response_yields_three_fiscal_years(self):
        collected, _ = self._ingest()
        self.assertEqual(sorted(collected["revenue"]),
                         ["2023-12-31", "2024-12-31", "2025-12-31"])

    def test_debt_matched_by_account_name(self):
        collected, tags = self._ingest()
        self.assertIn("shortTermDebt", collected)
        self.assertEqual(tags["shortTermDebt"], "-표준계정코드 미사용-")

    def test_fiscal_end_follows_accounting_month(self):
        self.assertEqual(dart._fiscal_end(2025, 12), "2025-12-31")
        self.assertEqual(dart._fiscal_end(2025, 3), "2025-03-31")
        self.assertEqual(dart._fiscal_end(2024, 2), "2024-02-29")
        self.assertEqual(dart._fiscal_end(2025, 2), "2025-02-28")

    def test_amount_parsing(self):
        self.assertEqual(dart._num("1,234,000"), 1234000.0)
        self.assertEqual(dart._num("-6,701"), -6701.0)
        self.assertIsNone(dart._num("-"))
        self.assertIsNone(dart._num(""))

    def test_controlling_interest_drives_roe(self):
        """한국 관행: ROE는 지배주주 기준으로 계산한다."""
        statements = {"annual": {
            "revenue": [{"end": "2025-12-31", "value": 1000.0}],
            "netIncome": [{"end": "2025-12-31", "value": 100.0}],
            "netIncomeOwners": [{"end": "2025-12-31", "value": 80.0}],
            "equity": [{"end": "2025-12-31", "value": 1000.0}],
            "equityOwners": [{"end": "2025-12-31", "value": 500.0}],
        }}
        m = met.compute_metrics(statements)
        self.assertEqual(m["profitability"]["roeBasis"], "controlling")
        self.assertAlmostEqual(m["profitability"]["roe"], 0.16)          # 80/500
        self.assertAlmostEqual(m["controllingInterest"]["minorityShareOfIncome"], 0.2)

    def test_us_path_keeps_consolidated_roe(self):
        statements = {"annual": {
            "revenue": [{"end": "2025-12-31", "value": 1000.0}],
            "netIncome": [{"end": "2025-12-31", "value": 100.0}],
            "equity": [{"end": "2025-12-31", "value": 500.0}],
        }}
        m = met.compute_metrics(statements)
        self.assertEqual(m["profitability"]["roeBasis"], "consolidated")
        self.assertAlmostEqual(m["profitability"]["roe"], 0.2)


class TestDcf(unittest.TestCase):
    BASE = {
        "baseRevenue": 1000, "sharesOutstanding": 100, "netDebt": 0,
        "currentPrice": 8.0, "taxRate": 0.0,
        "scenarios": {"base": {
            "revenueGrowth": [0, 0, 0, 0, 0], "operatingMargin": 0.10,
            "fcfConversion": 1.0, "wacc": 0.10, "terminalGrowth": 0.0, "probability": 1.0}},
    }

    def test_matches_hand_computation(self):
        # FCF 100 영구 / WACC 10% → EV 1000, 100주 → 주당 10, 현재가 8 → +25%
        b = dcf.run(self.BASE)["scenarios"]["base"]
        self.assertAlmostEqual(b["enterpriseValue"], 1000.0, places=6)
        self.assertAlmostEqual(b["fairValuePerShare"], 10.0, places=6)
        self.assertAlmostEqual(b["upside"], 0.25, places=6)

    def test_net_debt_reduces_equity(self):
        a = dict(self.BASE, netDebt=200)
        self.assertAlmostEqual(dcf.run(a)["scenarios"]["base"]["fairValuePerShare"], 8.0, places=6)

    def test_wacc_must_exceed_terminal_growth(self):
        a = {**self.BASE, "scenarios": {"base": {**self.BASE["scenarios"]["base"],
                                                 "wacc": 0.02, "terminalGrowth": 0.03}}}
        self.assertIn("error", dcf.run(a)["scenarios"]["base"])

    def test_warns_when_terminal_value_dominates(self):
        a = {**self.BASE, "scenarios": {"base": {**self.BASE["scenarios"]["base"],
                                                 "wacc": 0.08, "terminalGrowth": 0.06}}}
        self.assertTrue(any("잔존가치" in w for w in dcf.run(a)["warnings"]))

    def test_probability_mismatch_is_flagged(self):
        a = {**self.BASE, "scenarios": {"base": {**self.BASE["scenarios"]["base"], "probability": 0.5}}}
        self.assertTrue(any("확률 합" in w for w in dcf.run(a)["warnings"]))

    def test_requires_core_inputs(self):
        self.assertFalse(dcf.run({"sharesOutstanding": 10})["ok"])

    def test_sensitivity_grid_shape(self):
        s = dcf.run(self.BASE)["sensitivity"]
        self.assertEqual(len(s["fairValueGrid"]), 5)
        self.assertEqual(len(s["fairValueGrid"][0]), 5)


class TestScore(unittest.TestCase):
    def test_band_boundaries(self):
        cases = [(9.0, "STRONG BUY"), (8.99, "BUY"), (8.0, "BUY"), (7.99, "ACCUMULATE"),
                 (7.0, "ACCUMULATE"), (6.99, "HOLD"), (5.5, "HOLD"), (5.49, "REDUCE"),
                 (4.0, "REDUCE"), (3.99, "AVOID")]
        for value, expected in cases:
            self.assertEqual(score.band_for(value), expected, value)

    def test_weights_renormalize_when_sections_skipped(self):
        agg = score.weighted_score({"business": 8, "valuation": 6})
        self.assertAlmostEqual(sum(agg["weights"].values()), 1.0, places=6)
        self.assertAlmostEqual(agg["score"], 8 * 0.5 + 6 * 0.5, places=2)
        self.assertIn("growth", agg["skipped"])

    def test_great_company_expensive_price_is_not_strong_buy(self):
        """문서 §2.2 — 좋은 회사라도 비싸면 STRONG BUY가 나오면 안 된다."""
        r = score.run({"scores": {"business": 9.8, "growth": 9.8, "financial": 9.8,
                                  "valuation": 3.0, "technical": 7, "catalyst": 8, "risk": 6},
                       "coverage": {"ratio": 1.0}})
        self.assertNotEqual(r["proposedRating"], "STRONG BUY")

    def test_critical_flag_requires_downgrade_review(self):
        r = score.run({"scores": {"business": 9.5, "growth": 9.5, "financial": 9.5,
                                  "valuation": 9.5, "technical": 9, "catalyst": 9, "risk": 9},
                       "riskFlags": {"accounting": "high"}, "coverage": {"ratio": 1.0}})
        self.assertTrue(r["criticalRiskFlags"]["downgradeReviewRequired"])
        self.assertIn("하향", r["proposedRatingReason"])

    def test_insufficient_data_gate(self):
        r = score.run({"scores": {"business": 9}, "coverage": {"ratio": 0.4}})
        self.assertEqual(r["proposedRating"], "INSUFFICIENT DATA")

    def test_confidence_inverts_uncertainty_inputs(self):
        low = score.confidence({"dataQuality": 1, "dataFreshness": 1, "analystAgreement": 1,
                                "valuationUncertainty": 1, "eventRisk": 1})
        high = score.confidence({"dataQuality": 1, "dataFreshness": 1, "analystAgreement": 1,
                                 "valuationUncertainty": 0, "eventRisk": 0})
        self.assertLess(low["score"], high["score"])
        self.assertEqual(high["level"], "HIGH")


class TestFormat(unittest.TestCase):
    def test_krw_scales_to_jo_and_eok(self):
        self.assertEqual(fmt.money(1641e12, "KRW"), "1,641조원")
        self.assertEqual(fmt.money(9.5e12, "KRW"), "9.5조원")
        self.assertEqual(fmt.money(3.4e8, "KRW"), "3억원")

    def test_usd_scales_to_t_b_m(self):
        self.assertEqual(fmt.money(5.22e12, "USD"), "$5.22T")
        self.assertEqual(fmt.money(-2.1e9, "USD"), "-$2.1B")

    def test_missing_value_is_dash_not_zero(self):
        self.assertEqual(fmt.money(None, "KRW"), fmt.DASH)
        self.assertEqual(fmt.pct(None), fmt.DASH)
        self.assertEqual(fmt.multiple(None), fmt.DASH)

    def test_price_is_never_abbreviated(self):
        self.assertEqual(fmt.price(281500, "KRW"), "281,500원")
        self.assertEqual(fmt.price(214.72, "USD"), "$214.72")

    def test_percent_sign_and_zero(self):
        self.assertEqual(fmt.pct(0.039), "+3.9%")
        self.assertEqual(fmt.pct(-0.467), "-46.7%")
        self.assertEqual(fmt.pct(0), "0.0%")

    def test_bar_clamps_out_of_range(self):
        self.assertEqual(fmt.bar_pct(8.0), 80.0)
        self.assertEqual(fmt.bar_pct(12.0), 100.0)
        self.assertEqual(fmt.bar_pct(-3.0), 0.0)
        self.assertEqual(fmt.bar_pct(None), 0.0)

    def test_week52_position(self):
        self.assertEqual(fmt.week52_position(200, 100, 300), 50.0)
        self.assertIsNone(fmt.week52_position(200, 300, 100))


class TestRender(unittest.TestCase):
    def _report(self, **over):
        base = {
            "ticker": "005930.KS", "name": "삼성전자", "currency": "KRW",
            "mode": "quick", "analysisDate": "2026-08-23",
            "verdict": {"rating": "HOLD", "score": 7.11,
                        "confidence": {"score": 48, "level": "MEDIUM"},
                        "headline": "결론 한 문장"},
            "snapshot": {"price": 281500, "changePct": 0.039,
                         "marketCap": 1641e12, "asOf": "2026-08-21",
                         "week52": [67500, 374500]},
            "scores": [{"area": "Business", "value": 8.0, "weight": 0.2},
                       {"area": "Valuation", "value": 5.0, "weight": 0.2}],
            "sections": [{"title": f"S{i}", "body": "본문", "takeaway": "요약"} for i in range(2)],
            "scenarios": [{"name": "Bear", "fairValue": 150000, "upside": -0.47},
                          {"name": "Bull", "fairValue": 496000, "upside": 0.76}],
            "risks": [{"name": "R", "severity": "high", "note": "n"}],
            "criticalFlags": {"accounting": "low"},
            "changeMyMind": ["조건1", "조건2"],
            "sources": [{"tier": 1, "name": "DART", "asOf": "2026-08-22"}],
        }
        base.update(over)
        return base

    def test_quick_truncates_extra_sections_and_warns(self):
        r = self._report(sections=[{"title": f"S{i}", "body": "b", "takeaway": "t"}
                                   for i in range(8)])
        norm, warnings = render.normalize(r)
        self.assertEqual(len(norm["sections"]), 4)
        self.assertTrue(any("잘라냈다" in w for w in warnings))

    def test_deep_keeps_all_sections(self):
        r = self._report(mode="deep", sections=[{"title": f"S{i}", "body": "b", "takeaway": "t"}
                                                for i in range(8)])
        norm, warnings = render.normalize(r)
        self.assertEqual(len(norm["sections"]), 8)

    def test_body_trimmed_only_at_paragraph_boundary(self):
        long_body = "가" * 300 + "\n\n" + "나" * 300 + "\n\n" + "다" * 300
        r = self._report(sections=[{"title": "S", "body": long_body, "takeaway": "t"}])
        norm, warnings = render.normalize(r)
        kept = norm["sections"][0]["body"]
        self.assertTrue(any("예산" in w for w in warnings))
        # 문단 중간을 자르지 않았다 — 남은 길이는 문단 길이의 배수다
        self.assertIn(len(kept), (300, 604))

    def test_modes_without_scenarios_drop_them(self):
        norm, warnings = render.normalize(self._report(mode="technical"))
        self.assertEqual(norm["scenarios"], [])
        self.assertTrue(any("시나리오" in w for w in warnings))

    def test_scenario_axis_places_price_marker(self):
        norm, _ = render.normalize(self._report())
        axis = norm["_axis"]
        self.assertTrue(0 < axis["pricePos"] < 100)
        bear, bull = norm["scenarios"]
        self.assertLess(bear["_pos"], axis["pricePos"])
        self.assertGreater(bull["_pos"], axis["pricePos"])

    def test_currency_inferred_from_korean_ticker(self):
        r = self._report()
        del r["currency"]
        norm, _ = render.normalize(r)
        self.assertEqual(norm["currency"], "KRW")

    def test_brief_stays_short(self):
        self.assertLessEqual(len(render.brief(self._report()).splitlines()), 12)

    def test_markdown_has_rating_in_first_lines(self):
        head = render.markdown(self._report()).splitlines()[:4]
        self.assertTrue(any("HOLD" in ln for ln in head))

    def test_html_escapes_untrusted_text(self):
        r = self._report(name="A <script>alert(1)</script> & Co")
        out = report_html.render(*render.normalize(r))
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_no_color_defined_only_inside_a_theme_block(self):
        """다크 블록에만 정의된 색이 있으면 시스템 기본 상태에서 그 색이 빈다.

        이 스킬이 만드는 페이지는 뷰어 테마 3상태(light / dark / 미지정)에서 모두 읽혀야 한다.
        미디어쿼리와 [data-theme] 블록을 걷어낸 CSS만으로 모든 var()가 해소되어야 한다.
        """
        import re
        css = report_html.CSS
        stripped = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css, flags=re.S)
        stripped = re.sub(r":root\[data-theme[^{]*\{[^{}]*\}", "", stripped, flags=re.S)
        defined = set(re.findall(r"(--[\w-]+)\s*:", stripped))
        used = set(re.findall(r"var\((--[\w-]+)", css))
        inline_only = {"--p"}  # 시나리오 마커 위치는 style 속성으로 주입한다
        self.assertEqual(used - defined - inline_only, set())

    def test_both_theme_blocks_redefine_every_color(self):
        import re
        css = report_html.CSS
        root = re.search(r":root\{(.*?)\}", css, re.S).group(1)
        colors = {t for t in re.findall(r"(--[\w-]+):", root) if t != "--radius"}
        for pattern in (r'prefers-color-scheme: dark\)\{\s*:root:not\(\[data-theme="light"\]\)\{(.*?)\}',
                        r':root\[data-theme="dark"\]\{(.*?)\}'):
            block = re.search(pattern, css, re.S)
            self.assertIsNotNone(block, pattern)
            self.assertEqual(colors - set(re.findall(r"(--[\w-]+):", block.group(1))), set())

    def test_html_renders_missing_sections_as_unavailable(self):
        r = self._report(scenarios=[], unavailable=[{"section": "DCF", "reason": "적자 기업"}])
        out = report_html.render(*render.normalize(r))
        self.assertIn("분석 불가 영역", out)
        self.assertIn("적자 기업", out)

    def test_html_shows_quality_and_price_side_by_side(self):
        out = report_html.render(*render.normalize(self._report()))
        self.assertIn("Business Quality", out)
        self.assertIn("좋은 회사와 좋은 가격은 다른 문제다", out)


class TestValidate(unittest.TestCase):
    def test_missing_required_field_is_error(self):
        r = validate.validate_schema("technical", {"trend": "uptrend"})
        self.assertFalse(r["ok"])

    def test_bear_case_cannot_be_empty(self):
        r = validate.validate_schema("bear", {
            "thesis": [], "pricedInExpectations": ["x"], "thesisBreakers": [],
            "downsideScenario": {}, "overlookedRisks": [], "confidence": 0.5, "sources": []})
        self.assertFalse(r["ok"])
        self.assertTrue(any("Bear Case" in e for e in r["errors"]))

    def test_confidence_range_enforced(self):
        r = validate.validate_schema("technical", {
            "trend": "up", "levels": {}, "observations": [], "score": 5, "confidence": 87})
        self.assertTrue(any("confidence" in e for e in r["errors"]))

    def test_unknown_rating_rejected(self):
        r = validate.validate_schema("committee", {
            "finalRating": "SUPER BUY", "ratingRationale": "x", "strongestBullArgument": "x",
            "strongestBearArgument": "x", "pricedIn": "x",
            "whatWouldChangeMyMind": ["a", "b"], "metricsToMonitor": ["a"], "confidence": 0.6})
        self.assertFalse(r["ok"])

    def test_factcheck_flags_mismatch(self):
        ref = {"latest": {"revenue": 1000.0}}
        out = validate.factcheck({"citedFigures": [{"path": "latest.revenue", "value": 1500.0}]}, ref)
        self.assertFalse(out["ok"])
        self.assertEqual(out["flag"], "CONFLICTED DATA")

    def test_factcheck_accepts_within_tolerance(self):
        ref = {"latest": {"revenue": 1000.0}}
        out = validate.factcheck({"citedFigures": [{"path": "latest.revenue", "value": 1005.0}]}, ref)
        self.assertTrue(out["ok"])

    def test_factcheck_marks_unverifiable_paths(self):
        out = validate.factcheck({"citedFigures": [{"path": "nope.here", "value": 1}]}, {})
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["unverifiable"]), 1)

    def test_report_requires_headline_and_price(self):
        r = validate.validate_schema("report", {
            "ticker": "T", "name": "N", "mode": "quick", "analysisDate": "2026-08-23",
            "verdict": {"rating": "HOLD"}, "snapshot": {}, "sections": [],
            "changeMyMind": ["a"], "sources": []})
        self.assertFalse(r["ok"])
        joined = " ".join(r["errors"])
        self.assertIn("headline", joined)
        self.assertIn("price", joined)


if __name__ == "__main__":
    unittest.main()
