import os
import fitz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from django.db import models
from django.conf import settings
from django.utils import timezone
import requests
import json
from flows.models import GoogleOAuthToken, GoogleUserFile

DOCS_SCOPES = ['https://www.googleapis.com/auth/documents.readonly']
SHEETS_SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']


def get_credentials(scopes, token_file='token.json', credentials_file='credentials.json'):
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'w') as token:
            token.write(creds.to_json())

    return creds


def fetch_google_doc_text(doc_id: str) -> str:
    creds = get_credentials(DOCS_SCOPES)
    service = build('docs', 'v1', credentials=creds)

    try:
        doc = service.documents().get(documentId=doc_id).execute()

        content = []
        for element in doc.get("body", {}).get("content", []):
            text = extract_text_from_element(element)
            if text:
                content.append(text)
        return "\n".join(content).strip()
    except Exception as e:
        return f"[Error fetching Google Doc: {e}]"
    

def fetch_google_sheet_text(sheet_id: str, range_str: str = 'Sheet1') -> str:
    creds = get_credentials(SHEETS_SCOPES)
    service = build('sheets', 'v4', credentials=creds)

    try:
        sheet = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_str
        ).execute()

        rows = sheet.get('values', [])
        return "\n".join([" | ".join(row) for row in rows])
    except Exception as e:
        return f"[Error fetching Google Sheet: {e}]"


def extract_text_from_element(element) -> str:
    text = ""
    if 'paragraph' in element:
        for run in element['paragraph'].get('elements', []):
            if 'textRun' in run:
                text += run['textRun'].get('content', '')
    return text.strip()

def fetch_pdf_text(file_path: str) -> str:
    try:
        text = ""
        with fitz.open(file_path) as pdf:
            for page in pdf:
                text += page.get_text()
        return text.strip()
    except Exception as e:
        return f"[Error extracting PDF text: {e}]"

# --- Models ---


# --- Service Functions ---
GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_OAUTH_SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
]
GOOGLE_OAUTH_DEVICE_CODE_URL = 'https://oauth2.googleapis.com/device/code'
GOOGLE_OAUTH_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_OAUTH_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'

import datetime

def get_google_oauth_url():
    # Device flow: get device/user code
    data = {
        'client_id': GOOGLE_CLIENT_ID,
        'scope': ' '.join(GOOGLE_OAUTH_SCOPES),
    }
    resp = requests.post(GOOGLE_OAUTH_DEVICE_CODE_URL, data=data)
    resp.raise_for_status()
    return resp.json()  # Contains device_code, user_code, verification_url, expires_in, interval

def poll_for_token(device_code):
    data = {
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'device_code': device_code,
        'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
    }
    resp = requests.post(GOOGLE_OAUTH_TOKEN_URL, data=data)
    if resp.status_code == 200:
        return resp.json()
    return None

def store_google_token(user, token_data):
    expires_at = timezone.now() + datetime.timedelta(seconds=token_data['expires_in'])
    GoogleOAuthToken.objects.update_or_create(
        user=user,
        defaults={
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token', ''),
            'expires_at': expires_at,
            'scope': token_data.get('scope', ''),
            'token_type': token_data.get('token_type', ''),
        }
    )

def refresh_google_token(user):
    token = GoogleOAuthToken.objects.get(user=user)
    data = {
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'refresh_token': token.refresh_token,
        'grant_type': 'refresh_token',
    }
    resp = requests.post(GOOGLE_OAUTH_TOKEN_URL, data=data)
    resp.raise_for_status()
    token_data = resp.json()
    store_google_token(user, token_data)
    return token_data

def get_valid_access_token(user):
    token = GoogleOAuthToken.objects.get(user=user)
    if token.expires_at < timezone.now() + datetime.timedelta(minutes=2):
        refresh_google_token(user)
        token = GoogleOAuthToken.objects.get(user=user)
    return token.access_token

def validate_google_file_access(user, link):
    # Extract file_id and type from link
    if 'docs.google.com/document' in link:
        file_type = 'doc'
        file_id = link.split('/d/')[1].split('/')[0]
        api_url = f'https://docs.googleapis.com/v1/documents/{file_id}'
    elif 'docs.google.com/spreadsheets' in link:
        file_type = 'sheet'
        file_id = link.split('/d/')[1].split('/')[0]
        api_url = f'https://sheets.googleapis.com/v4/spreadsheets/{file_id}'
    else:
        return False, 'Invalid Google Docs/Sheets link.'
    access_token = get_valid_access_token(user)
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(api_url, headers=headers)
    if resp.status_code == 200:
        GoogleUserFile.objects.get_or_create(user=user, link=link, file_id=file_id, file_type=file_type)
        return True, 'File access validated.'
    return False, 'Could not access file with your Google account.'

def list_user_google_files(user):
    return list(GoogleUserFile.objects.filter(user=user).values('link', 'file_type', 'added_at'))
