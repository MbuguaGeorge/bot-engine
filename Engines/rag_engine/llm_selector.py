import os
import logging
from typing import Dict, Any, Optional, List
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel
from django.apps import apps

logger = logging.getLogger(__name__)

class LLMSelector:
    """Utility class to select and configure LLM based on user selection"""
    
    @staticmethod
    def get_llm(model_name: str) -> BaseChatModel:
        """Get LLM instance based on model name"""
        if model_name.startswith("gpt-"):
            return LLMSelector._get_openai_llm(model_name)
        elif model_name.startswith("claude-"):
            return LLMSelector._get_anthropic_llm(model_name)
        elif model_name.startswith("gemini-"):
            return LLMSelector._get_google_llm(model_name)
        else:
            raise ValueError(f"Unsupported model: {model_name}")
    
    @staticmethod
    def _get_openai_llm(model_name: str) -> ChatOpenAI:
        """Configure OpenAI LLM"""
        try:
            return ChatOpenAI(
                model=model_name,
                temperature=0.7,
                max_tokens=4000,
                openai_api_key=os.getenv("OPENAI_API_KEY")
            )
        except Exception as e:
            logger.error(f"Error configuring OpenAI LLM: {e}")
            raise
    
    @staticmethod
    def _get_anthropic_llm(model_name: str) -> ChatAnthropic:
        """Configure Anthropic LLM"""
        try:
            return ChatAnthropic(
                model=model_name,
                temperature=0.7,
                max_tokens=4000,
                anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
            )
        except Exception as e:
            logger.error(f"Error configuring Anthropic LLM: {e}")
            raise
    
    @staticmethod
    def _get_google_llm(model_name: str) -> ChatGoogleGenerativeAI:
        """Configure Google LLM"""
        try:
            return ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0.7,
                max_tokens=4000,
                google_api_key=os.getenv("GOOGLE_API_KEY")
            )
        except Exception as e:
            logger.error(f"Error configuring Google LLM: {e}")
            raise