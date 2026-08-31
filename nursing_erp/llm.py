"""LLM 调用封装 — 用于 OCR 结果的结构化与纠错。

供应商由环境变量决定（.env 为真源）：
    LLM_API_KEY / LLM_BASE_URL(完整 endpoint) / LLM_MODEL
旧键 DEEPSEEK_* 仍被读取作回退（2026-08 前的配置）。
当前供应商：本地 DGX vLLM ocicek/Qwen3.6-27B-NVFP4（2026-08-31 起，
服务端 dato-vision 已挂 no-think 模板 + max-model-len 32768）；
kimi 原配置见 .env 注释块 / .env.kimi.bak-20260831。

用法：
    from nursing_erp.llm import chat
    result = chat(system_prompt, user_prompt, temperature=0.3)

返回 LLM 的文本回复；出错时返回空字符串（调用方负责降级处理）。
"""

import logging
import os
import time

import httpx

logger = logging.getLogger("menu_ocr")


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key, "")
        if value:
            return value
    return default


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.3,
         max_tokens: int = 2000, retries: int = 2) -> str:
    """调用 LLM，返回文本回复。失败重试，仍失败返回空字符串。"""
    api_key = _env("LLM_API_KEY", "DEEPSEEK_API_KEY")
    base_url = _env(
        "LLM_BASE_URL", "DEEPSEEK_BASE_URL",
        default="https://api.moonshot.cn/v1/chat/completions",
    )
    model = _env("LLM_MODEL", "DEEPSEEK_MODEL", default="kimi-k2.6")

    if not api_key:
        logger.error("LLM 调用失败：LLM_API_KEY 未设置")
        return ""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
    }
    if "kimi" in model:
        # kimi-k2.6 是推理模型，只接受默认 temperature=1，传自定义值会被拒
        pass
    else:
        payload["temperature"] = temperature
    if "qwen" in model.lower():
        # 本地 Qwen3.6：该 NVFP4 构建默认开思考链（纯文本混在 content 里且可到 270s）。
        # 服务端已挂 no-think 模板，这里显式关双保险（模板丢失时仍走空思考块）。
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if "minimax" in model.lower():
        # MiniMax-M3 默认 adaptive 思考，思考文本以 <think> 标签混在 content 里；
        # 结构化场景关掉（2026-08-31 实测：关后短答 45 tok/1.9s，开则 ~700 思考 tok）。
        payload["thinking"] = {"type": "disabled"}

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120.0,  # kimi-k2.6 推理耗时较长
            )
            resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"].get("content") or "").strip()
            if content:
                return content
            # content 为空——推理模型会把 token 耗在 reasoning_content 上，
            # max_tokens 不够时 content 尚未生成就被截断。记录以便排查。
            rc = data["choices"][0]["message"].get("reasoning_content", "")
            logger.warning(
                "LLM 返回 content 为空 (model=%s, max_tokens=%d, reasoning_content 长度=%d)",
                model, max_tokens, len(rc),
            )
        except Exception as exc:
            last_err = exc
            logger.warning("LLM 调用失败 (第 %d/%d 次): %s", attempt + 1, retries + 1, exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s 退避重试
    logger.error("LLM 最终失败: %s", last_err)
    return ""
