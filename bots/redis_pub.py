import os
import json
import redis
from django.conf import settings

REDIS_URL = getattr(settings, 'REDIS_URL', os.getenv('REDIS_URL'))

_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL)
    return _redis_client

def publish_notification(payload: dict):
    client = get_redis_client()
    client.publish('notifications', json.dumps(payload)) 