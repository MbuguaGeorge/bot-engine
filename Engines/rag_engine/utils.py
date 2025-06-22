import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


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
