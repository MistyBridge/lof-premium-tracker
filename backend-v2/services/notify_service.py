"""
阿里云 DirectMail 邮件通知服务
使用 SingleSendMail API 发送预警触发邮件。
SDK 为同步调用，通过 asyncio.to_thread 包装为异步。
"""
import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger("notify")

# ── 配置 ────────────────────────────────────────────────────

_DM_ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID", "")
_DM_ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET", "")
_DM_ACCOUNT_NAME = os.getenv("ALIYUN_DM_ACCOUNT_NAME", "noreply")
_DM_FROM_ALIAS = os.getenv("ALIYUN_DM_FROM_ALIAS", "金快查")
_DM_DOMAIN = os.getenv("ALIYUN_DM_DOMAIN", "jinkuaicha.com")


def _build_sender() -> str:
    """构建发信地址：account@domain"""
    return f"{_DM_ACCOUNT_NAME}@{_DM_DOMAIN}"


# ── 核心发送 ────────────────────────────────────────────────


def _send_email_sync(to_address: str, subject: str, html_body: str) -> bool:
    """同步发送邮件（在 to_thread 中运行）"""
    from alibabacloud_dm20151123.client import Client as DMClient
    from alibabacloud_dm20151123 import models as dm_models
    from alibabacloud_tea_openapi import models as open_api_models

    config = open_api_models.Config(
        access_key_id=_DM_ACCESS_KEY_ID,
        access_key_secret=_DM_ACCESS_KEY_SECRET,
    )
    config.endpoint = "dm.aliyuncs.com"
    client = DMClient(config)

    request = dm_models.SingleSendMailRequest(
        account_name=_build_sender(),
        address_type=1,
        to_address=to_address,
        subject=subject,
        html_body=html_body,
        from_alias=_DM_FROM_ALIAS,
        reply_to_address="false",
    )

    try:
        response = client.single_send_mail(request)
        logger.info("邮件发送成功: to=%s, subject=%s, request_id=%s",
                     to_address, subject, response.body.request_id)
        return True
    except Exception as e:
        logger.error("邮件发送失败: to=%s, error=%s", to_address, e)
        return False


async def send_email(to_address: str, subject: str, html_body: str) -> bool:
    """
    异步发送邮件。
    失败时记录日志并返回 False，不阻塞主流程。
    """
    if not _DM_ACCESS_KEY_ID or not _DM_ACCESS_KEY_SECRET:
        logger.warning("阿里云 DM AK/SK 未配置，跳过邮件发送")
        return False

    try:
        return await asyncio.to_thread(_send_email_sync, to_address, subject, html_body)
    except Exception as e:
        logger.error("邮件发送异常: to=%s, error=%s", to_address, e)
        return False


# ── 预警邮件封装 ────────────────────────────────────────────


def _build_alert_html(alert_info: dict) -> str:
    """生成预警触发的 HTML 邮件内容"""
    fund_code = alert_info.get("fund_code", "--")
    fund_name = alert_info.get("fund_name", "--")
    condition_desc = alert_info.get("condition_desc", "--")
    current_value = alert_info.get("current_value", "--")
    trigger_time = alert_info.get("trigger_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    return f"""
    <div style="font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #1890ff, #722ed1); border-radius: 12px 12px 0 0; padding: 24px; text-align: center;">
            <h2 style="color: #fff; margin: 0; font-size: 20px;">🔔 金快查 · 预警触发</h2>
        </div>
        <div style="background: #fff; border: 1px solid #f0f0f0; border-top: none; border-radius: 0 0 12px 12px; padding: 24px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 15px;">
                <tr>
                    <td style="padding: 12px 0; color: #666; width: 100px;">基金代码</td>
                    <td style="padding: 12px 0; color: #333; font-weight: 600;">{fund_code}</td>
                </tr>
                <tr style="border-top: 1px solid #f5f5f5;">
                    <td style="padding: 12px 0; color: #666;">基金名称</td>
                    <td style="padding: 12px 0; color: #333;">{fund_name}</td>
                </tr>
                <tr style="border-top: 1px solid #f5f5f5;">
                    <td style="padding: 12px 0; color: #666;">触发条件</td>
                    <td style="padding: 12px 0; color: #333;">{condition_desc}</td>
                </tr>
                <tr style="border-top: 1px solid #f5f5f5;">
                    <td style="padding: 12px 0; color: #666;">当前值</td>
                    <td style="padding: 12px 0; color: #f5222d; font-weight: 700; font-size: 18px;">{current_value}</td>
                </tr>
                <tr style="border-top: 1px solid #f5f5f5;">
                    <td style="padding: 12px 0; color: #666;">触发时间</td>
                    <td style="padding: 12px 0; color: #333;">{trigger_time}</td>
                </tr>
            </table>
            <div style="margin-top: 24px; text-align: center;">
                <a href="https://lof-fund-monitor.pages.dev" style="display: inline-block; background: #1890ff; color: #fff; padding: 10px 28px; border-radius: 6px; text-decoration: none; font-size: 14px;">查看详情</a>
            </div>
        </div>
        <div style="text-align: center; color: #999; font-size: 12px; margin-top: 16px;">
            此邮件由金快查自动发送，请勿直接回复
        </div>
    </div>
    """


async def send_alert_email(user_email: str, alert_info: dict) -> bool:
    """
    发送预警触发邮件。
    alert_info 需包含：fund_code, fund_name, condition_desc, current_value, trigger_time
    """
    fund_code = alert_info.get("fund_code", "")
    subject = f"【金快查】预警触发 — {fund_code}"
    html_body = _build_alert_html(alert_info)
    return await send_email(user_email, subject, html_body)
