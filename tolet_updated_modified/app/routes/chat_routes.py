from fastapi import APIRouter

from pydantic import BaseModel

from services.ai_chat.chat_service import (
    ChatService
)


router = APIRouter(

    prefix="/api",

    tags=["Tolet AI"]
)

chat_service = ChatService()


class ChatRequest(

    BaseModel
):

    session_id: str

    query: str


@router.post("/chat")
async def chat(

    request: ChatRequest
):

    try:

        result = (
            chat_service.process_query(

                session_id=(
                    request.session_id
                ),

                query=(
                    request.query
                )
            )
        )

        return {

            "success": True,

            "data": result
        }

    except Exception as error:

        print(
            "Chat Route Error:",
            error
        )

        return {

            "success": False,

            "message": (
                "Internal server error."
            ),

            "data": None
        }