"""M7 调度层测试 - 4项"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from scheduler import create_scheduler, _failures, _ok, _fail


class TestScheduler:
    """调度器测试"""

    def test_create_scheduler(self):
        """测试1: 调度器创建成功"""
        sched = create_scheduler()
        assert sched is not None
        jobs = sched.get_jobs()
        assert len(jobs) == 9

    def test_job_ids(self):
        """测试2: 9个任务ID正确"""
        sched = create_scheduler()
        job_ids = {j.id for j in sched.get_jobs()}
        expected = {"scan_codes", "fetch_info", "fetch_realtime", "fetch_nav", "fetch_kline", "fetch_nav_qdii", "daily_save", "check_partitions", "check_calendar"}
        assert job_ids == expected

    def test_record_success_resets_failures(self):
        """测试3: 成功重置失败计数"""
        _failures["test_job"] = 5
        _ok("test_job", 100.0, 10)
        assert _failures["test_job"] == 0

    def test_record_failure_increments(self):
        """测试4: 失败递增计数"""
        _failures["test_job"] = 0
        _fail("test_job", ValueError("test error"))
        assert _failures["test_job"] == 1
        _fail("test_job", ValueError("test error 2"))
        assert _failures["test_job"] == 2
