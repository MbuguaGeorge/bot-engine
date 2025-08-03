#!/usr/bin/env python3
"""
Test script for token calculation functionality
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'API.settings')
django.setup()

from Engines.rag_engine.token_calculator import token_calculator

def test_token_calculation():
    """Test token calculation for different models"""
    
    # Test input and output
    input_text = "Hello, how are you today? I hope you're doing well."
    output_text = "I'm doing great, thank you for asking! How can I help you today?"
    
    print("=== Token Calculation Test ===\n")
    
    # Test OpenAI models
    openai_models = ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]
    for model in openai_models:
        result = token_calculator.calculate_tokens_for_model(input_text, output_text, model)
        cost = token_calculator.estimate_cost(result)
        
        print(f"OpenAI {model}:")
        print(f"  Input tokens: {result['input_tokens']}")
        print(f"  Output tokens: {result['output_tokens']}")
        print(f"  Total tokens: {result['total_tokens']}")
        print(f"  Estimated cost: ${cost['total_cost_usd']:.6f}")
        print()
    
    # Test Anthropic models
    anthropic_models = ["claude-3-5-sonnet", "claude-3-haiku", "claude-3-sonnet-20240229"]
    for model in anthropic_models:
        result = token_calculator.calculate_tokens_for_model(input_text, output_text, model)
        cost = token_calculator.estimate_cost(result)
        
        print(f"Anthropic {model}:")
        print(f"  Input tokens: {result['input_tokens']}")
        print(f"  Output tokens: {result['output_tokens']}")
        print(f"  Total tokens: {result['total_tokens']}")
        print(f"  Estimated cost: ${cost['total_cost_usd']:.6f}")
        print()
    
    # Test Google models
    gemini_models = ["gemini-1.5-pro", "gemini-1.5-flash"]
    for model in gemini_models:
        result = token_calculator.calculate_tokens_for_model(input_text, output_text, model)
        cost = token_calculator.estimate_cost(result)
        
        print(f"Google {model}:")
        print(f"  Input characters: {result['input_chars']}")
        print(f"  Output characters: {result['output_chars']}")
        print(f"  Total characters: {result['total_chars']}")
        print(f"  Estimated cost: ${cost['total_cost_usd']:.6f}")
        print()

if __name__ == "__main__":
    test_token_calculation() 