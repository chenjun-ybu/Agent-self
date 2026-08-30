"""
config.py — 配置管理

API 密钥通过以下方式（优先级从高到低）：
  1. 环境变量  DEEPSEEK_API_KEY
  2. 配置文件  config.json （本目录下，不提交到 GitHub）

也可直接在 config.json 中设置：
{
    "api_key": "sk-xxxxxxxxxxxx",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v4-flash"
}
"""

import os
import json

_CONFIG_CACHE = None


def get_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    config = {
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    }

    # 1) 配置文件
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config.json",
    )
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            file_cfg = json.load(f)
        for k, v in file_cfg.items():
            if v:
                config[k] = v

    # 2) 环境变量覆盖
    env_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if env_key:
        config["api_key"] = env_key
    env_url = os.environ.get("DEEPSEEK_BASE_URL", "")
    if env_url:
        config["base_url"] = env_url
    env_model = os.environ.get("DEEPSEEK_MODEL", "")
    if env_model:
        config["model"] = env_model

    _CONFIG_CACHE = config
    return config


def get_api_key() -> str:
    return get_config()["api_key"]


def is_configured() -> bool:
    return bool(get_config()["api_key"])
