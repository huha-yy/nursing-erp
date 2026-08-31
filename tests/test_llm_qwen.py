"""本地 qwen 切换钉 — 2026-08-31.

阶段 0 探针实测的两个坑，切换本地 Qwen3.6-27B（.env LLM_MODEL=ocicek/...）后必须钉住：

1. no-think 模式 JSON 少尾部闭括号（finish_reason=stop、311 字符缺 1 个 `}`，
   temp=0.1 确定性复现）→ meals.api._repair_truncated_json 补全 + 解析链走通
2. 该 NVFP4 构建默认开思考链（纯文本混 content、OCR 可拖到 273s）→
   llm.chat 对 qwen 模型必须带 chat_template_kwargs={"enable_thinking": False}
"""

from unittest.mock import MagicMock

import pytest

from meals.api import _llm_structure, _repair_truncated_json
from nursing_erp import llm

# 探针实测原文：结构化全对、纠错全对，唯独少最后一个 `}`（char 311 处截断）
BROKEN_MENU_JSON = (
    '{"周一": {"早餐": ["小米粥", "卤蛋", "拌三丝"], "午餐": ["黄焖鸡", "清炒西蓝花", '
    '"丝瓜汤", "杂粮饭"], "晚餐": ["麻婆豆腐", "拌海带", "冬瓜排骨"]}, "周二": {"早餐": '
    '["南瓜粥", "八宝粥", "凉拌黄瓜"], "午餐": ["土豆炖鸡", "清炒油麦菜", "山药汤"], '
    '"晚餐": ["清蒸鲈鱼", "凉拌菠菜", "小米饭"]}, "周三": {"早餐": ["黑米粥", "鹌鹑蛋", '
    '"拌莴笋丝"], "午餐": ["冬瓜排骨", "木耳炒蛋", "丝瓜汤", "炒南瓜"], "晚餐": '
    '["杂粮饭", "清炒生菜", "拌三丝"]}'
)


# ── _repair_truncated_json ─────────────────────────────────────


def test_repair_missing_closing_braces():
    """实测失败样本：少 1 个 `}` → 补全后可解析且内容不变。"""
    import json

    data = json.loads(_repair_truncated_json(BROKEN_MENU_JSON))
    assert data["周一"]["早餐"] == ["小米粥", "卤蛋", "拌三丝"]
    assert data["周三"]["晚餐"] == ["杂粮饭", "清炒生菜", "拌三丝"]


def test_repair_already_valid_passthrough():
    assert _repair_truncated_json('{"a": [1, 2]}') == '{"a": [1, 2]}'


def test_repair_truncated_mid_string():
    """截断在字符串中间：先补引号再补括号。"""
    assert _repair_truncated_json('{"a": "ab') == '{"a": "ab"}'


def test_repair_ignores_braces_inside_strings():
    """字符串里的 {}/引号转义不参与配对计数。"""
    import json

    assert json.loads(_repair_truncated_json('{"a": "x{y[\\"z"}')) == {"a": 'x{y["z'}


# ── _llm_structure 解析链（mock llm_chat 返回探针实测坏样本）────


@pytest.mark.django_db
def test_llm_structure_tolerates_missing_tail_brace(monkeypatch):
    monkeypatch.setattr("meals.api.llm_chat", lambda *a, **k: BROKEN_MENU_JSON)
    result = _llm_structure("OCR 原文（随便）", ["小米粥"], mode="menu")
    assert result["周一"]["早餐"][0] == "小米粥"
    assert set(result) == {"周一", "周二", "周三"}


# ── llm.chat qwen 分支 ──────────────────────────────────────────


def _capture_chat(model: str, monkeypatch) -> dict:
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(json or {})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [{"message": {"content": "ok", "reasoning_content": ""}}]
        }
        return resp

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://x/v1/chat/completions")
    monkeypatch.setenv("LLM_MODEL", model)
    assert llm.chat("sys", "user") == "ok"
    return captured


def test_chat_qwen_sends_no_think_kwarg(monkeypatch):
    """qwen 模型：带 temperature + chat_template_kwargs 关思考。"""
    p = _capture_chat("ocicek/Qwen3.6-27B-NVFP4", monkeypatch)
    assert p["chat_template_kwargs"] == {"enable_thinking": False}
    assert p["temperature"] == 0.3


def test_chat_kimi_keeps_quirks(monkeypatch):
    """kimi 模型：不传 temperature（推理模型怪癖），不带 qwen 的 kwargs。"""
    p = _capture_chat("kimi-k2.6", monkeypatch)
    assert "temperature" not in p
    assert "chat_template_kwargs" not in p
