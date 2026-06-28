from fastapi import FastAPI

from fastapi.middleware.cors import (
    CORSMiddleware
)

from routes.chat_routes import (
    router as chat_router
)


# ===================================
# FastAPI App
# ===================================
app = FastAPI(

    title="Tolet AI Backend",

    version="1.0.0"
)

# ===================================
# CORS
# ===================================
app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"]
)

# ===================================
# Routes
# ===================================
app.include_router(
    chat_router
)

# ===================================
# Root Endpoint
# ===================================
@app.get("/")
async def root():

    return {

        "message": (
            "Tolet AI Backend Running.."
        )
    }