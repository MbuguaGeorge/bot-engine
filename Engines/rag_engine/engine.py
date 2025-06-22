from openai import OpenAI
from .utils import fetch_pdf_text, fetch_google_sheet_text, fetch_google_doc_text


class RAGEngine:
    def __init__(
        self,
        model: str,
        system_prompt: str = None,
        pdf_file: str = None,
        google_sheet_url: str = None,
        google_doc_url: str = None,
        fallback_response: str = "Sorry, I couldn't find relevant information.",
        extra_instructions: str = None,
    ):
        self.client = OpenAI()
        self.model = model
        self.system_prompt = system_prompt
        self.pdf_file = pdf_file
        self.google_sheet_url = google_sheet_url
        self.google_doc_url = google_doc_url
        self.fallback_response = fallback_response
        self.extra_instructions = extra_instructions

    def gather_context(self, query: str) -> str:
        sources = []

        if self.pdf_file:
            sources.append(fetch_pdf_text(self.pdf_file))

        if self.google_sheet_url:
            sources.append(fetch_google_sheet_text(self.google_sheet_url))

        if self.google_doc_url:
            sources.append(fetch_google_doc_text(self.google_doc_url))

        return "\n\n".join(filter(None, sources))

    def build_prompt(self, query: str, context: str) -> str:
        parts = []

        if self.system_prompt:
            parts.append(self.system_prompt)

        if self.extra_instructions:
            parts.append(self.extra_instructions)

        if context:
            parts.append(f"Context:\n{context}")

        parts.append(f"User Question: {query}")
        parts.append("Answer:")

        return "\n\n".join(parts)

    def run(self, query: str) -> str:
        context = self.gather_context(query)

        if not context:
            return self.fallback_response

        prompt = self.build_prompt(query, context)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip()
