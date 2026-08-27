import os
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from prompt_injection import system_instruction
from services.ai_chat.chat_service import ChatService

load_dotenv()


router = APIRouter(
    prefix="/api",
    tags=["Tolet AI"]
)


chat_service = ChatService()

API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


chat_history = {}


class ChatRequest(BaseModel):
    session_id: str
    query: str

class Message(BaseModel):
    conversation_id: str
    message: str



@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    
    try:
        result = chat_service.process_query(
            session_id=request.session_id,
            query=request.query
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as error:
        print("Chat Route Error:", error)
        return {
            "success": False,
            "message": "Internal server error.",
            "data": None
        }


@router.post("/chat_tolu")
async def chat_tolu_endpoint(msg: Message):
    """
    Legacy/Alternative chat endpoint calling OpenRouter directly.
    """
    try:
        if msg.conversation_id not in chat_history:
            chat_history[msg.conversation_id] = []
            
        messages_payload = [
            {
                "role": "system",
                "content": system_instruction
            }
        ]
        
        recent_history = chat_history[msg.conversation_id][-10:]
        messages_payload.extend(recent_history)
        messages_payload.append({
            "role": "user",
            "content": msg.message
        })
        
        payload = {
            "model": "openai/gpt-4o-mini",
            "messages": messages_payload
        }
        
        response = requests.post(OPENROUTER_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        
        result = response.json()
        reply = result["choices"][0]["message"]["content"]
        
        chat_history[msg.conversation_id].append({"role": "user", "content": msg.message})
        chat_history[msg.conversation_id].append({"role": "assistant", "content": reply})
        chat_history[msg.conversation_id] = chat_history[msg.conversation_id][-20:]

        if len(chat_history[msg.conversation_id]) > 25:

            chat_history[msg.conversation_id].clear()
        
        return {"reply": reply}

    except Exception as error:
        print("Chat Tolu Route Error:", error)
        raise HTTPException(status_code=500, detail="Failed to process OpenRouter request.")
