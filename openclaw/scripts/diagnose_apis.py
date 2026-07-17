"""Quick API key diagnostics for all 4 LLM providers."""
import asyncio, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")


async def test_one(name: str, api_key: str, base_url: str, model: str, endpoint: str = "/chat/completions"):
    print(f"\n{'='*50}")
    print(f"Testing {name}: {model}")
    print(f"URL: {base_url}{endpoint}")
    key_preview = api_key[:15] + "..." if len(api_key) > 15 else (api_key or "EMPTY")
    print(f"Key: {key_preview}")
    print(f"{'='*50}")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
            resp = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "回复 OK"}],
                    "max_tokens": 10,
                },
            )
            print(f"Status: {resp.status_code}")
            body = resp.text[:500]
            print(f"Body: {body}")
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    print(f"  Output: {choices[0].get('message', {}).get('content', '')}")
                else:
                    # Try Baidu format
                    result = data.get("result") or data.get("output") or data
                    print(f"  Output: {str(result)[:200]}")
            return resp.status_code
    except Exception as e:
        print(f"ERROR: {e}")
        return None


async def main():
    keys = [
        ("DeepSeek", os.getenv("DEEPSEEK_API_KEY", ""), "https://api.deepseek.com", "deepseek-chat"),
        ("Doubao",   os.getenv("DOUBAO_API_KEY", ""),   "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-2-0-pro-260215"),
        ("Qwen",     os.getenv("QWEN_API_KEY", ""),     "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        ("Wenxin",   os.getenv("WENXIN_API_KEY", ""),   "https://qianfan.baidubce.com/v2", "ernie-4.0-turbo-128k"),
    ]
    results = {}
    for name, key, url, model in keys:
        status = await test_one(name, key, url, model)
        results[name] = status

    print(f"\n{'='*50}")
    print("SUMMARY:")
    for name, status in results.items():
        status_str = "OK" if status == 200 else f"FAIL({status})"
        print(f"  {name:10s}: {status_str}")

if __name__ == "__main__":
    asyncio.run(main())
