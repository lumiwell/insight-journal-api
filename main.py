import os
from pathlib import Path
from typing import List, Literal, cast
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from dotenv import load_dotenv
import json

from fastapi.middleware.cors import CORSMiddleware

# 加载 .env 文件中的环境变量
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. 声明支持多轮对话的数据模型
# ==========================================
class Message(BaseModel):
    role: Literal["user", "assistant", "system"]      # 角色："user", "assistant" 或 "system"
    content: str   # 消息内容

class ChatRequest(BaseModel):
    messages: List[Message]  # 接收前端传来的历史消息数组

# ==========================================
# 2. 全局配置与环境变量读取
# ==========================================
API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not API_KEY:
    raise RuntimeError("🚨 环境变量 DASHSCOPE_API_KEY 未设置！请检查 .env 文件。")

BASE_URL = "https://ws-c56yietppdmtmf3m.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen3.7-max"

aclient = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# ==========================================
# 防御性 Prompt 动态加载机制
# ==========================================
def load_system_prompt() -> str:
    """
    优先读取被 Git 忽略的生产环境私有提示词，
    若不存在（如开源仓库克隆者），则降级读取公开的 sample 提示词。
    """
    base_dir = Path(__file__).parent / "prompts"
    prod_path = base_dir / "system_prod.md"
    sample_path = base_dir / "system_sample.md"

    # 1. 尝试加载私密核心资产
    if prod_path.exists():
        with open(prod_path, "r", encoding="utf-8") as file:
            return file.read()
    
    # 2. 降级加载开源脱敏版本
    try:
        with open(sample_path, "r", encoding="utf-8") as file:
            print("⚠️ 警告: 未找到生产级 Prompt，正在使用开源 Sample 提示词启动。")
            return file.read()
    except FileNotFoundError:
        return "你是一个心理辅助树洞。" # 极限兜底

# 每次服务启动时加载
SYSTEM_PROMPT = load_system_prompt()

@app.post("/api/v1/chat")
async def handle_diary_chat(request: ChatRequest):
    # 动态组装 Payload：System Prompt 永远在第一位，紧接着拼接前端传来的历史对话记录
    formatted_messages: List[ChatCompletionMessageParam] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # 遍历前端传来的消息，组装进上下文中
    for msg in request.messages:
        formatted_messages.append(cast(ChatCompletionMessageParam, {"role": msg.role, "content": msg.content}))

    async def generate():
        try:
            stream = await aclient.chat.completions.create(
                model=MODEL_NAME,
                messages=formatted_messages,
                temperature=0.7,
                stream=True
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    # 按照用户要求，返回 data: {content}\n\n 格式
                    # 为了避免 content 中的换行符破坏 SSE 格式，这里使用 json.dumps 序列化
                    yield f"data: {json.dumps(content, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            # 捕获异常时也尽量保持 SSE 格式，通知客户端错误信息
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    # 必须使用 StreamingResponse，并指定 media_type="text/event-stream"
    return StreamingResponse(generate(), media_type="text/event-stream")