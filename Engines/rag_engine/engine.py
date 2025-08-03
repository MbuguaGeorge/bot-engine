from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_pinecone import PineconeVectorStore
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from typing import Any, List, Dict
from pinecone import Pinecone
from django.conf import settings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.runnables import Runnable
from .token_calculator import token_calculator
from .llm_selector import LLMSelector
import logging

logger = logging.getLogger(__name__)

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
        # Get the selected model from node data
        self.model = node["data"].get("model", "gpt-4o-mini")
        self.llm = LLMSelector.get_llm(self.model)
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
        self.token_usage = None
        self.cost_estimate = None

    def gather_context(self, query: str) -> str:
        results = []

        uploaded_files = self.context.get("files", [])
        gdrive_links = self.context.get("gdrive_links", [])

        # Determine number of documents to retrieve based on query complexity
        query_length = len(query.strip())
        if query_length < 10:  # Simple queries like "hello"
            k = 2  # Fewer documents for simple queries
        elif query_length < 50:  # Medium queries
            k = 3
        else:  # Complex queries
            k = 5  # Default

        logger.info(f"Query length: {query_length}, retrieving {k} documents")

        for file in uploaded_files:
            file_id = str(file)
            metadata_filter = {
                "user_id": str(self.context.get("user_id")),
                "bot_id": str(self.context.get("bot_id")),
                "flow_id": str(self.context.get("flow_id")),
                "file_id": str(file_id)
            }
            docs = self.vector_utils.query(query=query, filter=metadata_filter, k=k)
            results.extend(docs)

        for link in gdrive_links:
            metadata_filter = {
                "user_id": self.context.get("user_id"),
                "bot_id": self.context.get("bot_id"),
                "flow_id": self.context.get("flow_id"),
                "link": str(link)
            }
            docs = self.vector_utils.query(query=query, filter=metadata_filter, k=k)
            results.extend(docs)

        # Join context and limit length to reduce token usage
        context_text = "\n\n".join([doc.page_content for doc in results])
        
        # Limit context to reasonable size (approximately 2000 tokens)
        max_context_chars = 8000  # Roughly 2000 tokens for most models
        if len(context_text) > max_context_chars:
            logger.warning(f"Context too long ({len(context_text)} chars), truncating to {max_context_chars} chars")
            context_text = context_text[:max_context_chars] + "... [truncated]"
        
        logger.info(f"Context gathered: {len(results)} documents, {len(context_text)} chars")
        return context_text

    def run(self, query: str) -> Dict[str, Any]:
        """Run RAG engine and return response with token usage"""
        try:
            # For very simple queries, skip context to save tokens
            query_length = len(query.strip())
            if query_length < 5:  # Very simple queries like "hi", "hello"
                logger.info(f"Simple query detected ({query_length} chars), skipping context")
                context = ""
            else:
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

            # Prepare the input for the chain
            chain_input = {
            "system_prompt": self.system_prompt,
            "extra_instructions": self.extra_instructions,
            "context": context,
            "question": query,
            }

            # Get the response
            result = chain.invoke(chain_input)
            response_content = result.content.strip()

            # Calculate token usage
            full_prompt = prompt.format(**chain_input)
            
            # Debug logging to identify token usage breakdown
            logger.info(f"=== TOKEN USAGE BREAKDOWN ===")
            logger.info(f"System prompt length: {len(self.system_prompt)} chars")
            logger.info(f"Extra instructions length: {len(self.extra_instructions)} chars")
            logger.info(f"Context length: {len(context)} chars")
            logger.info(f"User query length: {len(query)} chars")
            logger.info(f"Full prompt length: {len(full_prompt)} chars")
            logger.info(f"Response length: {len(response_content)} chars")
            
            self.token_usage = token_calculator.calculate_tokens_for_model(
                input_text=full_prompt,
                output_text=response_content,
                model=self.model
            )

            # Estimate cost
            self.cost_estimate = token_calculator.estimate_cost(self.token_usage)

            # Log usage for debugging
            logger.info(f"RAG Engine Usage - Model: {self.model}, "
                       f"Input tokens: {self.token_usage.get('input_tokens', 0)}, "
                       f"Output tokens: {self.token_usage.get('output_tokens', 0)}, "
                       f"Cost: ${self.cost_estimate.get('total_cost_usd', 0):.6f}")
            logger.info(f"=== END TOKEN BREAKDOWN ===")

            return {
                "response": response_content,
                "token_usage": self.token_usage,
                "cost_estimate": self.cost_estimate,
                "model": self.model,
                "context_length": len(context),
                "query_length": len(query)
            }

        except Exception as e:
            logger.error(f"Error in RAG engine: {e}")
            return {
                "response": self.fallback_response,
                "token_usage": {
                    "provider": "unknown",
                    "model": self.model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "cost_estimate": {
                    "input_cost_usd": 0,
                    "output_cost_usd": 0,
                    "total_cost_usd": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "model": self.model,
                "context_length": 0,
                "query_length": len(query),
                "error": str(e)
            }

    def get_token_usage(self) -> Dict[str, Any]:
        """Get the last token usage information"""
        return self.token_usage or {}

    def get_cost_estimate(self) -> Dict[str, Any]:
        """Get the last cost estimate"""
        return self.cost_estimate or {}