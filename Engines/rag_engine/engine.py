from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_pinecone import PineconeVectorStore
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from typing import Any, List
from pinecone import Pinecone
from django.conf import settings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.runnables import Runnable

class VectorStoreUtils:
    def __init__(self, index_name: str, api_key: str):
        pc = Pinecone(api_key=api_key)
        self.index = pc.Index(index_name)
        self.embeddings = OpenAIEmbeddings()
        self.vectorstore = PineconeVectorStore(index_name=index_name, embedding=self.embeddings)

    def upsert_documents(self, text: str, metadata: dict):
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_text(text)
        docs = [Document(page_content=chunk, metadata=metadata) for chunk in chunks]
        self.vectorstore.add_documents(docs)

    def query(self, query: str, filter: dict, k: int = 5):
        return self.vectorstore.similarity_search(query=query, k=k, filter=filter)


class RAGEngine:
    def __init__(self, node: dict[str, Any], context: dict[str, Any]):
        self.model = node["data"].get("model", "gpt-4o-mini")
        self.llm = ChatOpenAI(model=self.model)
        self.system_prompt = node["data"].get("systemPrompt", "")
        self.pdf_file = node["data"].get("pdfFile", "")
        self.google_sheet_url = node["data"].get("googleSheetUrl", "")
        self.google_doc_url = node["data"].get("googleDocUrl", "")
        self.fallback_response = node["data"].get("fallbackResponse", "Sorry, I can't answer that right now.")
        self.extra_instructions = node["data"].get("extraInstructions", "")
        self.context = context
        self.vector_utils = VectorStoreUtils(
            index_name=settings.PINECONE_INDEX_NAME,
            api_key=settings.PINECONE_API_KEY,
        )

    def gather_context(self, query: str) -> str:
        results = []

        uploaded_files = self.context.get("files", [])
        gdrive_links = self.context.get("gdrive_links", [])

        for file in uploaded_files:
            file_id = str(file)
            metadata_filter = {
                "user_id": str(self.context.get("user_id")),
                "bot_id": str(self.context.get("bot_id")),
                "flow_id": str(self.context.get("flow_id")),
                "file_id": str(file_id)
            }
            docs = self.vector_utils.query(query=query, filter=metadata_filter)
            results.extend(docs)

        for link in gdrive_links:
            metadata_filter = {
                "user_id": self.context.get("user_id"),
                "bot_id": self.context.get("bot_id"),
                "flow_id": self.context.get("flow_id"),
                "link": link
            }
            docs = self.vector_utils.query(query=query, filter=metadata_filter)
            results.extend(docs)

        return "\n\n".join([doc.page_content for doc in results])


    def run(self, query: str) -> str:
        context = self.gather_context(query) or ""

        template = """
        {system_prompt}

        {extra_instructions}

        Context:
        {context}

        User Question: {question}
        Answer:
        """
        prompt = PromptTemplate(
            input_variables=["system_prompt", "extra_instructions", "context", "question"],
            template=template.strip(),
        )

        chain: Runnable = prompt | self.llm

        result = chain.invoke({
            "system_prompt": self.system_prompt,
            "extra_instructions": self.extra_instructions,
            "context": context,
            "question": query,
        })

        return result.content.strip()