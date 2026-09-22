"""M7 调度层测试。

2026-09-23 修正：本文件长期断言"9 个任务"，而调度器实际早已是 12 个
（`est_nav` / `save_est_nav` / `reload_calendar` / `fetch_holdings` 都是后来加的，
测试一直没跟上，自那以后一直是失败状态）。断言已改为反映真实的任务集合 ——
一个永远失败的测试等于没有测试。
"""
import pytest
from apscheduler.triggers.cron import CronTrigger

from scheduler import create_scheduler, _failures, _ok, _fail

# 与 create_scheduler() 一一对应；改动调度必须同步改这里
EXPECTED_JOB_IDS = {
    "scan_codes", "fetch_info", "fetch_realtime", "fetch_nav", "fetch_kline",
    "daily_save", "check_partitions", "check_calendar",
    "est_nav", "save_est_nav", "reload_calendar", "fetch_holdings",
}


class TestScheduler:
    """调度器测试"""

    def test_create_scheduler(self):
        sched = create_scheduler()
        assert sched is not None
        assert len(sched.get_jobs()) == len(EXPECTED_JOB_IDS)

    def test_job_ids(self):
        job_ids = {j.id for j in create_scheduler().get_jobs()}
        assert job_ids == EXPECTED_JOB_IDS

    def test_fetch_nav_runs_every_two_hours(self):
        """净值采集从"每天 08:00 一次"改为每 2 小时一次。

        跨境/QDII 净值要等海外收盘后披露（傍晚到深夜），每天只跑一次会让
        页面在净值已公布、我们却没入库的窗口里挂着旧净值。
        """
        jobs = {j.id: j for j in create_scheduler().get_jobs()}
        trigger = jobs["fetch_nav"].trigger
        assert isinstance(trigger, CronTrigger)
        assert str(trigger.fields[5]) == "*/2", "fetch_nav 应每 2 小时触发"

    def test_fetch_nav_qdii_no_longer_scheduled(self):
        """28 只 QDII 全部已在采集名单内，单独再跑一遍是重复请求。"""
        ids = {j.id for j in create_scheduler().get_jobs()}
        assert "fetch_nav_qdii" not in ids

    @pytest.mark.asyncio
    async def test_record_success_resets_failures(self):
        _failures["test_job"] = 5
        _ok("test_job", 100.0, 10)
        assert _failures["test_job"] == 0

    @pytest.mark.asyncio
    async def test_record_failure_increments(self):
        _failures["test_job"] = 0
        _fail("test_job", ValueError("test error"))
        assert _failures["test_job"] == 1
        _fail("test_job", ValueError("test error 2"))
        assert _failures["test_job"] == 2
