from .utils import fetch_google_sheet_text, fetch_google_doc_text, fetch_pdf_text
from pinecone import Pinecone
from .engine import VectorStoreUtils
from django.conf import settings
from celery import shared_task, Celery
from celery.schedules import crontab
from flows.models import GoogleDocCache, Flow, UploadedFile
import hashlib
import logging

logger = logging.getLogger('celery')

app = Celery('API')

def compute_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

@shared_task
def upsert_pdf_to_pinecone(file_id, user_id, bot_id, flow_id, node_id):
    try:
        file_obj = UploadedFile.objects.get(id=file_id)
        file_path = file_obj.file.path

        # Extract text based on file type
        text = fetch_pdf_text(file_path)

        # Upsert to Pinecone
        vector_utils = VectorStoreUtils(
            index_name=settings.PINECONE_INDEX_NAME,
            api_key=settings.PINECONE_API_KEY,
        )
        metadata = {
            'user_id': str(user_id),
            'bot_id': str(bot_id),
            'flow_id': str(flow_id),
            'file_id': str(file_id),
            'node_id': str(node_id) if node_id is not None else None
        }
        vector_utils.upsert_documents(text, metadata)
    except Exception as e:
        logger.error(f"Error in upsert_file_to_pinecone: {e}")
        raise e


@shared_task
def delete_pdf_from_pinecone(file_id, user_id, bot_id, flow_id, node_id):
    filter_metadata = {
        'user_id': str(user_id),
        'bot_id': str(bot_id),
        'flow_id': str(flow_id),
        'file_id': str(file_id),
        'node_id': str(node_id) if node_id is not None else None
    }

    try:
        index = Pinecone(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX_NAME)
        index.delete(filter=filter_metadata)
    except Exception as e:
        logger.error(f"Error in delete_pdf_from_pinecone: {e}")
        raise e


def upsert_gdrive_links_to_pinecone(user, flow_id, link):
    logger.info(f"Running upsert_gdrive_links_to_pinecone for flow_id={flow_id}, link={link}")
    flow = Flow.objects.get(id=flow_id)
    if 'docs.google.com/document' in link:
        doc_id = link.split('/d/')[1].split('/')[0]
        text = fetch_google_doc_text(doc_id, user)
    elif 'docs.google.com/spreadsheets' in link:
        sheet_id = link.split('/d/')[1].split('/')[0]
        text = fetch_google_sheet_text(sheet_id, user)
    else:
        return

    content_hash = compute_hash(text)
    cache, _ = GoogleDocCache.objects.get_or_create(link=link, flow=flow)
    if cache.last_hash != content_hash:
        vector_utils = VectorStoreUtils(
            index_name=settings.PINECONE_INDEX_NAME,
            api_key=settings.PINECONE_API_KEY,
        )
        metadata = {
            'user_id': flow.bot.user.id,
            'bot_id': flow.bot.id,
            'flow_id': flow.id,
            'link': link
        }
        try:
            vector_utils.upsert_documents(text, metadata)
            cache.last_hash = content_hash
            cache.save()
        except Exception as e:
            logger.error(f"Pinecone upsert error: {e}") 

# Register periodic task
app.conf.beat_schedule = {
    'upsert-gdrive-links-every-2-hours': {
        'task': 'Engines.rag_engine.tasks.upsert_gdrive_links_to_pinecone, Engines.rag_engine.tasks.upsert_pdf_to_pinecone, Engines.rag_engine.tasks.delete_pdf_from_pinecone',
        'schedule': crontab(hour='*/2'),
    },
}