"""DeepSeek LLM 调用封装 — 用于 OCR 结果的结构化与纠错。

用法：
    from nursing_erp.llm import chat
    result = chat(system_prompt, user_prompt, temperature=0.3)

返回 LLM 的文本回复；出错时返回空字符串（调用方负责降级处理）。
"""

import os
import time
import logging
import httpx

logger = logging.getLogger("menu_ocr")


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.3,
         max_tokens: int = 2000, retries: int = 2) -> str:
    """调用 DeepSeek，返回文本回复。失败重试，仍失败返回空字符串。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key:
        logger.error("DeepSeek 调用失败：DEEPSEEK_API_KEY 未设置")
        return ""

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if content:
                return content
            # content 为空——推理模型会把 token 耗在 reasoning_content 上，
            # max_tokens 不够时 content 尚未生成就被截断。记录以便排查。
            rc = data["choices"][0]["message"].get("reasoning_content", "")
            logger.warning(
                "DeepSeek 返回 content 为空 (model=%s, max_tokens=%d, reasoning_content 长度=%d)",
                model, max_tokens, len(rc),
            )
        except Exception as exc:
            last_err = exc
            logger.warning("DeepSeek 调用失败 (第 %d/%d 次): %s", attempt + 1, retries + 1, exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s 退避重试
    logger.error("DeepSeek 最终失败: %s", last_err)
    return ""
