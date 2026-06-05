#!/usr/bin/env python3
"""Wrapper for run_agent_direct.py that adds execution logging instrumentation.

Intercepts agent calls to log:
- Execution time (latency_ms)
- Token usage (tokens_in, tokens_out)
- Success/failure outcomes
- Error messages
- Task context

All logs are environment-tagged (prod) and sensitive data is redacted.
"""

import time

# Import the instrumented logger
from tools.skills_logger_v2 import log_skill

# Re-export key functions from run_agent_direct for backward compatibility
# (This would be in the actual implementation - here we show the pattern)


def run_agent_with_logging(
    agent_name: str,
    message: str,
    model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    max_tokens: int = 4096,
) -> dict:
    """Run an agent and log the execution.

    This is a wrapper around the original run_agent() from run_agent_direct.py
    that adds execution logging.

    Args:
        agent_name: Name of the agent
        message: Input message/task
        model: Model to use
        max_tokens: Maximum output tokens

    Returns:
        Result dict with 'success', 'output', 'model', 'usage' keys
    """
    # Import here to avoid circular dependencies
    import sys as sys_module

    original_module = sys_module.modules.get("tools.run_agent_direct")
    if not original_module:
        # Would need to import run_agent_direct.py
        raise ImportError("run_agent_direct module not loaded")

    start_time = time.time()
    start_tokens_in = estimate_prompt_tokens(message)

    try:
        # Call original run_agent function
        result = original_module.run_agent(agent_name, message, model, max_tokens)

        # Calculate metrics
        latency_ms = (time.time() - start_time) * 1000
        output_text = result.get("output", "")
        tokens_out = estimate_completion_tokens(output_text)
        cost_usd = estimate_cost(start_tokens_in, tokens_out, model)

        # Log execution
        log_skill(
            skill_name=agent_name,
            task_context=message[:200],  # First 200 chars of message
            inputs={
                "message_len": len(message),
                "model": model,
                "max_tokens": max_tokens,
            },
            outputs={
                "output_len": len(output_text),
                "success": result.get("success", True),
            },
            latency_ms=latency_ms,
            tokens_in=start_tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            success=result.get("success", True),
            environment="prod",
        )

        return result

    except Exception as e:
        # Log failure
        latency_ms = (time.time() - start_time) * 1000
        log_skill(
            skill_name=agent_name,
            task_context=message[:200],
            inputs={
                "message_len": len(message),
                "model": model,
            },
            outputs={},
            latency_ms=latency_ms,
            tokens_in=start_tokens_in,
            tokens_out=0,
            cost_usd=0,
            success=False,
            error=str(e)[:500],
            environment="prod",
        )

        raise


def estimate_prompt_tokens(text: str) -> int:
    """Rough estimate of tokens in prompt text (1 token ≈ 4 chars)."""
    return max(1, len(text) // 4)


def estimate_completion_tokens(text: str) -> int:
    """Rough estimate of tokens in completion text."""
    return max(1, len(text) // 4)


def estimate_cost(tokens_in: int, tokens_out: int, model: str) -> float:
    """Estimate cost based on token counts and model.

    Pricing (as of 2026-06):
    - Llama 3.3 70B via Together: ~$0.0008/1k input, ~$0.001/1k output
    - Claude: ~$0.003/1k input, ~$0.015/1k output
    """
    if "claude" in model.lower():
        return (tokens_in * 0.000003) + (tokens_out * 0.000015)
    else:  # Llama/Together
        return (tokens_in * 0.0000008) + (tokens_out * 0.0000010)


# Integration points for instrumentation:
# 1. In run_agent_direct.py's run_agent() function:
#    - Call log_skill() after successful execution
#    - Call log_skill() on exception with success=False
#
# 2. In agent_heartbeat_checks.py's check_* functions:
#    - Log each check as a "skill" named "{agent_name}_check"
#    - Log success/failure based on check result
#
# Usage pattern:
#
#   from tools.skills_logger_v2 import log_skill
#   import time
#
#   start = time.time()
#   try:
#       result = do_work()
#       log_skill(
#           skill_name="my-skill",
#           task_context="description of what we did",
#           inputs={"input_field": "value"},
#           outputs={"output_field": result},
#           latency_ms=(time.time() - start) * 1000,
#           success=True,
#       )
#   except Exception as e:
#       log_skill(
#           skill_name="my-skill",
#           task_context="description of what we did",
#           inputs={},
#           outputs={},
#           latency_ms=(time.time() - start) * 1000,
#           success=False,
#           error=str(e),
#       )


if __name__ == "__main__":
    print("""
Skills Execution Logger Integration Guide
==========================================

To integrate into run_agent_direct.py:

1. Add import at top of file:
   from tools.skills_logger_v2 import log_skill
   import time

2. Wrap the LLM call in run_agent():

   start = time.time()
   try:
       # ... existing LLM call ...
       result = llm_call(...)

       # Log success
       log_skill(
           skill_name=agent_name,
           task_context=message[:200],
           inputs={...},
           outputs={...},
           latency_ms=(time.time()-start)*1000,
           tokens_in=prompt_tokens,
           tokens_out=completion_tokens,
           cost_usd=estimated_cost,
           success=True,
       )
   except Exception as e:
       # Log failure
       log_skill(
           skill_name=agent_name,
           ...,
           success=False,
           error=str(e),
       )
       raise

3. Add similar logging to agent_heartbeat_checks.py:
   - Wrap each check_* function
   - Log the check result (success/failure)
   - Use skill_name="{agent_name}_check"

Safety constraints enforced by v2 logger:
✓ Automatic PII/credential redaction
✓ Environment tagging (prod vs test)
✓ Minimum sample-size rules (5+ execs)
✓ Minimum feedback thresholds (3+ points)
✓ Advisory-only recommendations
✓ 7-day observation period before routing changes
""")
