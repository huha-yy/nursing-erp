"""DeepSeek LLM 调用封装 — 用于 OCR 结果的结构化与纠错。

用法：
    from nursing_erp.llm import chat
    result = chat(system_prompt, user_prompt, temperature=0.3)

返回 LLM 的文本回复；出错时返回空字符串（调用方负责降级处理）。
"""

import os
import httpx


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.3,
         max_tokens: int = 2000) -> str:
    """调用 DeepSeek，返回文本回复。失败返回空字符串。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if not api_key:
        return ""

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
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""
