import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.llm_client import config_problem
from app.api.routes import analytics, auth, chat, clients, feed, feedback, insights, meta, news
from app.config import get_settings

settings = get_settings()
settings.check_prod_secrets()

if problem := config_problem():
    logging.getLogger("uvicorn.error").warning(
        "%s: new insights, chat and news tagging will return 503 (see .env.example)", problem)

app = FastAPI(
    title="Alfa News Insights API",
    version="0.1.0",
    description="Персонализированная новостная аналитика для руководителей крупного бизнеса",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(clients.router, prefix="/api/clients", tags=["clients"])
app.include_router(feed.router, prefix="/api/feed", tags=["feed"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(insights.router, prefix="/api/insights", tags=["insights"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(meta.router, prefix="/api/meta", tags=["meta"])


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "env": settings.app_env}
