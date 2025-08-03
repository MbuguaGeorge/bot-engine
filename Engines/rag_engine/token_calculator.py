import openai
import anthropic
import tiktoken
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class TokenCalculator:
    """Token calculation utilities for different AI providers"""
    
    def __init__(self):
        self.openai_encoding_cache = {}
    
    def get_openai_token_usage(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract token usage from OpenAI response"""
        try:
            usage = response.get("usage", {})
            return {
                "provider": "openai",
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
        except Exception as e:
            logger.error(f"Error extracting OpenAI token usage: {e}")
            return {
                "provider": "openai",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
    
    def count_openai_tokens(self, text: str, model: str = "gpt-4o") -> int:
        """Count tokens for OpenAI models using tiktoken"""
        try:
            if model not in self.openai_encoding_cache:
                self.openai_encoding_cache[model] = tiktoken.encoding_for_model(model)
            
            encoding = self.openai_encoding_cache[model]
            return len(encoding.encode(text))
        except Exception as e:
            logger.error(f"Error counting OpenAI tokens: {e}")
            return 0
    
    def count_claude_tokens(self, text: str, model: str = "claude-3-sonnet-20240229") -> int:
        """Count tokens for Claude models using character-based estimation"""
        try:
            # Claude tokens are roughly 1 token per 4 characters
            # This is a reasonable approximation for cost estimation
            estimated_tokens = len(text) // 4
            
            # Add some variance based on model type
            if "haiku" in model:
                # Haiku is more efficient, slightly fewer tokens
                estimated_tokens = int(estimated_tokens * 0.9)
            elif "opus" in model:
                # Opus might be slightly more verbose
                estimated_tokens = int(estimated_tokens * 1.1)
            
            return max(estimated_tokens, 1)  # Ensure at least 1 token
            
        except Exception as e:
            logger.error(f"Error counting Claude tokens: {e}")
            # Fallback: simple character-based estimation
            return len(text) // 4
    
    def count_gemini_characters(self, input_text: str, output_text: str = "") -> Dict[str, Any]:
        """Count characters for Gemini models"""
        try:
            return {
                "provider": "gemini",
                "input_chars": len(input_text),
                "output_chars": len(output_text),
                "total_chars": len(input_text) + len(output_text),
            }
        except Exception as e:
            logger.error(f"Error counting Gemini characters: {e}")
            return {
                "provider": "gemini",
                "input_chars": 0,
                "output_chars": 0,
                "total_chars": 0,
            }
    
    def calculate_tokens_for_model(self, input_text: str, output_text: str = "", model: str = "gpt-4o") -> Dict[str, Any]:
        """Calculate tokens/characters for any supported model"""
        try:
            # Determine provider from model name
            if model.startswith("gpt-") or model.startswith("text-"):
                input_tokens = self.count_openai_tokens(input_text, model)
                output_tokens = self.count_openai_tokens(output_text, model)
                return {
                    "provider": "openai",
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            elif model.startswith("claude-"):
                input_tokens = self.count_claude_tokens(input_text, model)
                output_tokens = self.count_claude_tokens(output_text, model)
                return {
                    "provider": "anthropic",
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            elif model.startswith("gemini-"):
                char_count = self.count_gemini_characters(input_text, output_text)
                char_count["model"] = model
                return char_count
            else:
                # Default to OpenAI for unknown models
                input_tokens = self.count_openai_tokens(input_text, "gpt-4o")
                output_tokens = self.count_openai_tokens(output_text, "gpt-4o")
                return {
                    "provider": "openai",
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
        except Exception as e:
            logger.error(f"Error calculating tokens for model {model}: {e}")
            return {
                "provider": "unknown",
                "model": model,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
    
    def estimate_cost(self, token_info: Dict[str, Any]) -> Dict[str, Any]:
        """Estimate cost based on token usage and model"""
        try:
            provider = token_info.get("provider", "unknown")
            model = token_info.get("model", "")
            input_tokens = token_info.get("input_tokens", 0)
            output_tokens = token_info.get("output_tokens", 0)
            
            # Cost per 1K tokens (approximate rates as of 2024)
            cost_rates = {
                "openai": {
                    "gpt-4o": {"input": 0.005, "output": 0.005},
                    "gpt-4o-mini": {"input": 0.00015, "output": 0.00015},
                    "gpt-4": {"input": 0.03, "output": 0.06},
                    "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
                },
                "anthropic": {
                    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
                    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
                    "claude-3-opus": {"input": 0.015, "output": 0.075},
                    "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
                },
                "google": {
                    "gemini-1.5-pro": {"input": 0.0035, "output": 0.0105},
                    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
                }
            }
            
            # Get rates for the specific model
            rates = cost_rates.get(provider, {}).get(model, {"input": 0.001, "output": 0.002})
            
            input_cost = (input_tokens / 1000) * rates["input"]
            output_cost = (output_tokens / 1000) * rates["output"]
            total_cost = input_cost + output_cost
            
            return {
                "input_cost_usd": round(input_cost, 6),
                "output_cost_usd": round(output_cost, 6),
                "total_cost_usd": round(total_cost, 6),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
        except Exception as e:
            logger.error(f"Error estimating cost: {e}")
            return {
                "input_cost_usd": 0,
                "output_cost_usd": 0,
                "total_cost_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }

# Global instance
token_calculator = TokenCalculator() 