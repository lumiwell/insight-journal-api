import os
from pathlib import Path
from typing import List, Literal, cast
import uuid
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from dotenv import load_dotenv
import json

from fastapi.middleware.cors import CORSMiddleware
from sqlmodel.ext.asyncio.session import AsyncSession
from database import get_session
from crud import get_or_create_session, save_message, get_recent_messages

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
class MessageModel(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    session_id: str
    message: MessageModel

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
    base_dir = Path(__file__).parent / "prompts"
    prod_path = base_dir / "system_prod.md"
    sample_path = base_dir / "system_sample.md"
    if prod_path.exists():
        with open(prod_path, "r", encoding="utf-8") as file:
            return file.read()
    try:
        with open(sample_path, "r", encoding="utf-8") as file:
            print("⚠️ 警告: 未找到生产级 Prompt，正在使用开源 Sample 提示词启动。")
            return file.read()
    except FileNotFoundError:
        return "你是一个心理辅助树洞。"

SYSTEM_PROMPT = load_system_prompt()

@app.post("/api/v1/chat")
async def handle_diary_chat(request: ChatRequest, db: AsyncSession = Depends(get_session)):
    try:
        session_id_uuid = uuid.UUID(request.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")

    # 1. 获取或创建会话
    await get_or_create_session(db, session_id_uuid)

    # 2. 落库最新的用户消息
    await save_message(db, session_id_uuid, request.message.role, request.message.content)

    # 3. 滑动窗口拉取历史并倒序（按时间正序）
    recent_messages = await get_recent_messages(db, session_id_uuid, limit=30)

    # 4. 组装 Payload：System Prompt 永远在第一位
    formatted_messages: List[ChatCompletionMessageParam] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in recent_messages:
        formatted_messages.append(cast(ChatCompletionMessageParam, {"role": msg.role, "content": msg.content}))

    async def generate():
        full_response_chunks = []
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
                    full_response_chunks.append(content)
                    yield f"data: {json.dumps(content, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            
            # AI 回复生成完毕后，将其落库
            full_response_text = "".join(full_response_chunks)
            if full_response_text:
                await save_message(db, session_id_uuid, "assistant", full_response_text)
                
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            
            # 即使中间报错中断，只要有部分回复也尽力保存下来
            full_response_text = "".join(full_response_chunks)
            if full_response_text:
                try:
                    await save_message(db, session_id_uuid, "assistant", full_response_text + "\n[Error: Stream Interrupted]")
                except Exception as save_err:
                    print(f"Failed to save partial AI message: {save_err}")

    return StreamingResponse(generate(), media_type="text/event-stream")