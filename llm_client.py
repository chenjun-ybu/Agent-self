"""
llm_client.py — DeepSeek LLM API 封装

提供统一的 chat() 接口，供 Agent 调用。
DeepSeek API 兼容 OpenAI 格式，使用 /v1/chat/completions 端点。

使用方式：
    from llm_client import LLMClient
    client = LLMClient()                       # 从 config.json 或环境变量读取密钥
    client = LLMClient(api_key="sk-xxx")       # 直接传入密钥

    reply = client.chat([
        {"role": "system", "content": "你是一个化学数据处理助手"},
        {"role": "user", "content": "分析这批数据的问题"},
    ])
"""

import json
import urllib.request
import urllib.error
from typing import Optional

from config import get_config


class LLMClient:
    """DeepSeek LLM 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        cfg = get_config()
        self.api_key = api_key or cfg["api_key"]
        self.base_url = base_url or cfg["base_url"]
        self.model = model or cfg["model"]

    def is_ready(self) -> bool:
        """检查 API 密钥是否已配置"""
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """
        发送聊天请求并返回助手回复文本。

        Args:
            messages:    消息列表 [{"role": "system|user|assistant", "content": "..."}]
            temperature: 采样温度 (0-2)
            max_tokens:  最大生成 token 数

        Returns:
            助手回复的文本内容

        Raises:
            RuntimeError: API 密钥未配置或调用失败
        """
        if not self.is_ready():
            raise RuntimeError(
                "DeepSeek API 密钥未配置。请在 config.json 中设置 api_key，"
                "或设置环境变量 DEEPSEEK_API_KEY。"
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                pass
            raise RuntimeError(
                f"DeepSeek API 调用失败 (HTTP {e.code}): {err_body}"
            )
        except urllib.error.URLError as e:
            raise RuntimeError(f"DeepSeek API 网络错误: {e.reason}")

    def analyze(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
        """便捷方法：单轮分析"""
        return self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
