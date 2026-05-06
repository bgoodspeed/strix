# Thinking Block Modification Bug Fix

## Issue Summary

**Problem**: Multiple Strix agents were failing with this error:
```
litellm.BadRequestError: AnthropicException - messages.X.content.Y: `thinking` or `redacted_thinking` blocks in the latest assistant message cannot be modified. These blocks must remain as they were in the original response.
```

**Root Cause**: The `_prepare_messages()` method in `strix/llm/llm.py` was directly modifying the original conversation history reference, corrupting the agent's conversation state.

**Impact**: Agents would work for the first few tool calls, then fail when trying to make subsequent LLM calls due to corrupted conversation state.

## Technical Details

### The Bug (Lines 205-206 in `strix/llm/llm.py`)

```python
def _prepare_messages(self, conversation_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # ... preparation code ...
    
    sanitized_history = self._sanitize_conversation_history(conversation_history)
    compressed = list(self.memory_compressor.compress_history(sanitized_history))
    
    # BUG: These lines corrupted the original conversation_history reference
    conversation_history.clear()      # ← Cleared agent's state.messages
    conversation_history.extend(compressed)  # ← Replaced with compressed version
    
    messages.extend(compressed)
    return messages
```

### The Problem Flow

1. Agent calls `self.llm.generate(self.state.get_conversation_history())`
2. `_prepare_messages()` receives **reference** to `state.messages` as `conversation_history`
3. Method clears and replaces the original list → **corrupts agent state**
4. Next LLM call gets corrupted state containing modified thinking blocks
5. Claude API rejects the request with thinking block modification error

### The Fix

**Removed the problematic lines** that modified the original reference:

```python
def _prepare_messages(self, conversation_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # ... preparation code ...
    
    sanitized_history = self._sanitize_conversation_history(conversation_history)
    compressed = list(self.memory_compressor.compress_history(sanitized_history))
    
    # FIXED: No longer modifies the original conversation_history
    messages.extend(compressed)
    return messages
```

## Verification

### Test Results

The fix was verified with `test_simple_fix_verification.py`:

```
1️⃣  Testing BUGGY behavior (old code):
   Original conversation length: 2
   After buggy_prepare_messages: 2
   Was original modified? True          ← BUG: Original was corrupted
   Original still has thinking blocks? False
   ❌ BUG: Original conversation was corrupted!

2️⃣  Testing FIXED behavior (new code):
   Original conversation length: 2
   Prepared messages length: 2
   Was original modified? False         ← FIXED: Original preserved
   Original still has thinking blocks? True
   Prepared messages have immutable thinking blocks? False
   ✅ FIXED: Original preserved, prepared messages cleaned!
```

### Failed Agents Fixed

This fix resolves the failures of these agents in scan run `grow-441e-75040-beta-clio-dev_1306`:

- **Mass Assignment Testing Agent** (agent_554180a2) - failed on `messages.1.content.1`
- **XSS Discovery Agent** (agent_7f12b02d) - failed on `messages.1.content.1`
- **IDOR Discovery Agent** (agent_a8a5a04c) - failed on `messages.3.content.1`

## Related Files Modified

1. **Fixed**: `strix/llm/llm.py` (lines 205-206 removed)
2. **Enhanced**: `scripts/monitor-scan.sh` (now correctly counts `llm_failed` agents)  
3. **Added**: `scripts/diagnose-thinking-errors.py` (diagnostic tool for this class of errors)
4. **Added**: `tests/llm/test_llm_sanitization.py::test_prepare_messages_preserves_original_conversation_history` (regression test)

## Prevention

The sanitization logic in `_sanitize_conversation_history()` already exists to prevent thinking block API errors. The bug was not in sanitization but in the conversation state management that followed.

**Key Principle**: Never modify parameter references that point to agent state. Always create new lists/objects for API preparation.

## Health Monitoring Enhancement

Updated `monitor-scan.sh` to properly detect `llm_failed` status:

```python
# Count actual failures including llm_failed
actual_failed = status['summary']['failed']
llm_failed_count = len([a for a in status['agents'] if a['status'] == 'llm_failed'])
total_failed = actual_failed + llm_failed_count
```

The script now correctly reports failure rates and can detect thinking block errors specifically.