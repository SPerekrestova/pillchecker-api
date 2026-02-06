from fastapi import APIRouter

from app.data import ddinter_store

router = APIRouter()


@router.get("/health")
async def health():
    ner_loaded = False
    try:
        from app.nlp import ner_model
        ner_loaded = ner_model._ner_pipeline is not None
    except ImportError:
        pass

    return {
        "status": "ok",
        "service": "pillchecker-api",
        "version": "0.1.0",
        "ner_model_loaded": ner_loaded,
        "interaction_pairs": ddinter_store.interaction_count(),
    }
