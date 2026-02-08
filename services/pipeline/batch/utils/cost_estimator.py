"""
Cost estimation utilities for OpenAI Batch API processing.

Provides functions to estimate costs for batch processing jobs based on
token counts and pricing models.

OpenAI Batch API Pricing (as of 2025):
- 50% discount compared to synchronous API
- gpt-4o-mini: $0.15/1M input tokens, $0.60/1M output tokens (batch)
- gpt-4o: $2.50/1M input tokens, $10.00/1M output tokens (batch)
"""
import tiktoken
from typing import Dict, List


# Pricing per 1M tokens (Batch API - 50% discount applied)
BATCH_PRICING = {
    'gpt-4o-mini': {
        'input': 0.075,  # $0.075 per 1M input tokens
        'output': 0.30,  # $0.30 per 1M output tokens
    },
    'gpt-4o': {
        'input': 1.25,  # $1.25 per 1M input tokens
        'output': 5.00,  # $5.00 per 1M output tokens
    },
    'gpt-4-turbo': {
        'input': 5.00,  # $5.00 per 1M input tokens
        'output': 15.00,  # $15.00 per 1M output tokens
    }
}

# Default model for cost estimation
DEFAULT_MODEL = 'gpt-4o-mini'

# Default output token estimate (conservative)
DEFAULT_OUTPUT_TOKENS = 300


def calculate_token_count(text: str, model: str = DEFAULT_MODEL) -> int:
    """
    Calculate token count for a given text using tiktoken.

    Args:
        text: Input text to count tokens
        model: Model name (for tokenizer selection)

    Returns:
        Number of tokens

    Example:
        >>> text = "This is a test message."
        >>> tokens = calculate_token_count(text)
        >>> print(f"Token count: {tokens}")
    """
    try:
        # Map model names to tiktoken encodings
        if 'gpt-4' in model.lower():
            encoding = tiktoken.encoding_for_model("gpt-4")
        elif 'gpt-3.5' in model.lower():
            encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        else:
            # Default to cl100k_base encoding (used by gpt-4, gpt-3.5-turbo, text-embedding-ada-002)
            encoding = tiktoken.get_encoding("cl100k_base")

        tokens = encoding.encode(text)
        return len(tokens)
    except Exception:
        # Fallback: rough estimate (4 characters per token)
        return len(text) // 4


def calculate_message_tokens(messages: List[Dict[str, str]], model: str = DEFAULT_MODEL) -> int:
    """
    Calculate token count for a list of messages (OpenAI chat format).

    Accounts for message formatting overhead.

    Args:
        messages: List of message dictionaries with 'role' and 'content'
        model: Model name

    Returns:
        Total token count including formatting overhead

    Example:
        >>> messages = [
        ...     {"role": "system", "content": "You are a helpful assistant."},
        ...     {"role": "user", "content": "Hello!"}
        ... ]
        >>> tokens = calculate_message_tokens(messages)
    """
    try:
        encoding = tiktoken.encoding_for_model("gpt-4")
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    # Message formatting overhead (approximate)
    # Each message has: <|start|>role\n{content}<|end|>\n
    tokens_per_message = 4  # Overhead per message
    tokens_per_name = 1  # If name field is present

    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if value:
                num_tokens += len(encoding.encode(str(value)))
            if key == "name":
                num_tokens += tokens_per_name

    num_tokens += 2  # Priming tokens for assistant response

    return num_tokens


def estimate_batch_cost(
    num_requests: int,
    avg_input_tokens: int,
    avg_output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    model: str = DEFAULT_MODEL
) -> Dict[str, float]:
    """
    Estimate cost for a batch processing job.

    Args:
        num_requests: Number of requests in the batch
        avg_input_tokens: Average input tokens per request
        avg_output_tokens: Average output tokens per request (default: 300)
        model: Model name (default: 'gpt-4o-mini')

    Returns:
        Dictionary with cost breakdown:
        - input_cost: Cost for input tokens
        - output_cost: Cost for output tokens
        - total_cost: Total estimated cost
        - per_request_cost: Average cost per request

    Example:
        >>> cost = estimate_batch_cost(1000, 500, 300, 'gpt-4o-mini')
        >>> print(f"Estimated total cost: ${cost['total_cost']:.2f}")
        >>> print(f"Cost per request: ${cost['per_request_cost']:.4f}")
    """
    if model not in BATCH_PRICING:
        raise ValueError(f"Unknown model: {model}. Available models: {list(BATCH_PRICING.keys())}")

    pricing = BATCH_PRICING[model]

    # Calculate total tokens
    total_input_tokens = num_requests * avg_input_tokens
    total_output_tokens = num_requests * avg_output_tokens

    # Calculate costs (pricing is per 1M tokens)
    input_cost = (total_input_tokens / 1_000_000) * pricing['input']
    output_cost = (total_output_tokens / 1_000_000) * pricing['output']
    total_cost = input_cost + output_cost

    return {
        'input_cost': round(input_cost, 4),
        'output_cost': round(output_cost, 4),
        'total_cost': round(total_cost, 4),
        'per_request_cost': round(total_cost / num_requests, 6) if num_requests > 0 else 0.0,
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'model': model
    }


def estimate_jsonl_file_cost(
    file_path: str,
    avg_output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    model: str = DEFAULT_MODEL
) -> Dict[str, float]:
    """
    Estimate cost for a JSONL batch input file.

    Reads the file and calculates actual input token counts.

    Args:
        file_path: Path to JSONL file with batch requests
        avg_output_tokens: Average output tokens per request
        model: Model name

    Returns:
        Cost breakdown dictionary (same as estimate_batch_cost)

    Example:
        >>> cost = estimate_jsonl_file_cost('batch_input.jsonl')
        >>> print(f"Estimated cost: ${cost['total_cost']:.2f}")
    """
    from .jsonl_utils import read_jsonl

    num_requests = 0
    total_input_tokens = 0

    for record in read_jsonl(file_path):
        num_requests += 1

        # Extract messages from request body
        body = record.get('body', {})
        messages = body.get('messages', [])

        if messages:
            tokens = calculate_message_tokens(messages, model)
            total_input_tokens += tokens

    if num_requests == 0:
        return {
            'input_cost': 0.0,
            'output_cost': 0.0,
            'total_cost': 0.0,
            'per_request_cost': 0.0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'model': model
        }

    avg_input_tokens = total_input_tokens // num_requests

    return estimate_batch_cost(num_requests, avg_input_tokens, avg_output_tokens, model)


def compare_sync_vs_batch_cost(
    num_requests: int,
    avg_input_tokens: int,
    avg_output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    model: str = DEFAULT_MODEL
) -> Dict[str, float]:
    """
    Compare cost between synchronous API and Batch API.

    Args:
        num_requests: Number of requests
        avg_input_tokens: Average input tokens per request
        avg_output_tokens: Average output tokens per request
        model: Model name

    Returns:
        Dictionary with:
        - sync_cost: Cost using synchronous API
        - batch_cost: Cost using Batch API
        - savings: Absolute savings
        - savings_percent: Percentage savings

    Example:
        >>> comparison = compare_sync_vs_batch_cost(1000, 500, 300, 'gpt-4o-mini')
        >>> print(f"Batch savings: ${comparison['savings']:.2f} ({comparison['savings_percent']}%)")
    """
    batch_cost_data = estimate_batch_cost(num_requests, avg_input_tokens, avg_output_tokens, model)
    batch_cost = batch_cost_data['total_cost']

    # Synchronous API costs (double the batch price)
    sync_cost = batch_cost * 2

    savings = sync_cost - batch_cost
    savings_percent = round((savings / sync_cost) * 100, 1) if sync_cost > 0 else 0.0

    return {
        'sync_cost': round(sync_cost, 4),
        'batch_cost': round(batch_cost, 4),
        'savings': round(savings, 4),
        'savings_percent': savings_percent,
        'model': model,
        'num_requests': num_requests
    }


def calculate_batch_time_estimate(
    num_requests: int,
    avg_processing_time_per_request: float = 3.0
) -> Dict[str, float]:
    """
    Estimate processing time for batch job.

    OpenAI Batch API has a 24-hour completion window, but typically
    completes much faster depending on load.

    Args:
        num_requests: Number of requests in batch
        avg_processing_time_per_request: Average processing time (seconds)

    Returns:
        Dictionary with time estimates:
        - estimated_processing_time_hours: Estimated time
        - max_completion_time_hours: Maximum (24 hours per OpenAI SLA)
        - estimated_vs_sync_speedup: Speedup factor vs sync processing

    Example:
        >>> time_est = calculate_batch_time_estimate(1000)
        >>> print(f"Estimated completion: {time_est['estimated_processing_time_hours']:.1f} hours")
    """
    # Estimated batch processing time (assuming parallelization)
    # OpenAI processes requests in parallel, so actual time is much less
    # than num_requests * processing_time
    estimated_time_seconds = num_requests * avg_processing_time_per_request * 0.1  # Assume 10x parallelization
    estimated_time_hours = estimated_time_seconds / 3600

    # Sync processing time (10-second rate limit)
    sync_time_seconds = num_requests * 10  # 10-second minimum between calls
    sync_time_hours = sync_time_seconds / 3600

    speedup = sync_time_hours / max(estimated_time_hours, 0.01)

    return {
        'estimated_processing_time_hours': round(estimated_time_hours, 2),
        'max_completion_time_hours': 24.0,  # OpenAI SLA
        'estimated_vs_sync_speedup': round(speedup, 1),
        'sync_processing_time_hours': round(sync_time_hours, 2),
        'num_requests': num_requests
    }
