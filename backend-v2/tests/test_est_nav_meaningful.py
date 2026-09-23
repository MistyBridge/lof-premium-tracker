"""估算净值（est_nav）的展示门槛与时间戳测试。

两处真实缺陷（2026-09-23 由用户报告 501225 引出）：

1. **"没有输入"的估算被当成估算值展示。**
   501225 景顺长城全球半导体芯片 QDII-LOF 实测：
       coverage = 0.03%, est_change_pct = 0.0000, est_nav == nav（原样拷贝）
   估算器一个价格输入都没有（既无持仓、也无可用指数行情），算出来的"估算净值"
   就是上一日净值的副本，页面却顺着算出「估算溢价率 +23.89%」。

2. **时间标签是假的。**
   前端 `_estNavTimeLabel()` 返回 `new Date()`（浏览器当前时间），把几小时前
   算出来的估算值盖上"刚刚"的戳 —— 实测页面显示 22:37，而估算在 19:57 就
   算完了，之后没再刷新（est_nav 只在 9:25–20:00 运行，现已延到 23:00）。
"""
from services.fund_service import _est_is_meaningful, _est_time_label


class TestEstIsMeaningful:
    def test_zero_coverage_zero_change_is_not_meaningful(self):
        """501225 的真实取值：est_nav 就是基准净值的副本。"""
        assert _est_is_meaningful({
            "est_nav": 3.1076, "nav": 3.1076,
            "est_change_pct": 0.0, "coverage": 0.03,
        }) is False

    def test_nonzero_change_is_meaningful(self):
        """159509 的真实取值：真的按持仓+指数算出了涨跌。"""
        assert _est_is_meaningful({
            "est_nav": 2.3866, "nav": 2.3833,
            "est_change_pct": 0.14, "coverage": 72.51,
        }) is True

    def test_zero_change_but_value_differs_is_meaningful(self):
        assert _est_is_meaningful({
            "est_nav": 1.01, "nav": 1.00, "est_change_pct": 0.0,
        }) is True

    def test_none_est_nav_is_not_meaningful(self):
        assert _est_is_meaningful({"est_nav": None, "nav": 1.0}) is False

    def test_missing_change_is_treated_as_zero(self):
        assert _est_is_meaningful({"est_nav": 1.0, "nav": 1.0}) is False

    def test_missing_base_nav_is_not_meaningful(self):
        """涨跌幅为 0 又拿不到基准净值 → 无法证明它不是副本，不展示。"""
        assert _est_is_meaningful({"est_nav": 1.0, "est_change_pct": 0.0}) is False

    def test_low_coverage_with_index_contribution_is_kept(self):
        """coverage 低但指数行情可用时估算依然成立，不能按阈值一刀切。"""
        assert _est_is_meaningful({
            "est_nav": 1.05, "nav": 1.00,
            "est_change_pct": 5.0, "coverage": 0.5,
        }) is True

    def test_junk_values_do_not_crash(self):
        assert _est_is_meaningful({
            "est_nav": "abc", "nav": 1.0, "est_change_pct": 0.0,
        }) is False
        assert _est_is_meaningful({
            "est_nav": 1.0, "nav": "x", "est_change_pct": 0.0,
        }) is False
        assert _est_is_meaningful({
            "est_nav": 1.0, "nav": 1.0, "est_change_pct": "abc",
        }) is False


class TestEstTimeLabel:
    def test_formats_hh_mm_from_iso(self):
        assert _est_time_label({"updated_at": "2026-09-23T19:57:02+08:00"}) == "19:57"

    def test_none_when_missing(self):
        assert _est_time_label(None) is None
        assert _est_time_label({}) is None
        assert _est_time_label({"updated_at": None}) is None

    def test_none_on_bad_value(self):
        assert _est_time_label({"updated_at": "not-a-time"}) is None
