import pytest
from unittest.mock import Mock, patch

from strix.llm.config import LLMConfig
from strix.llm.llm import LLM


@pytest.fixture
def llm():
    """Create an LLM instance for testing."""
    config = LLMConfig(model_name="openai/gpt-4")
    return LLM(config, agent_name="test-agent")


def test_sanitize_conversation_history_removes_immutable_thinking_blocks(llm):
    """Test that immutable thinking blocks are removed from conversation history."""
    messages = [
        {
            "role": "user",
            "content": "Test message"
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "This is normal content"
                },
                {
                    "type": "thinking",
                    "content": "This is thinking content",
                    "immutable": True
                },
                {
                    "type": "redacted_thinking",
                    "content": "This is redacted thinking",
                    "immutable": True
                }
            ]
        }
    ]

    sanitized = llm._sanitize_conversation_history(messages)

    # Should have same number of messages
    assert len(sanitized) == 2

    # First message should be unchanged
    assert sanitized[0] == messages[0]

    # Second message should have thinking blocks removed
    assert sanitized[1]["role"] == "assistant"
    assert len(sanitized[1]["content"]) == 1
    assert sanitized[1]["content"][0]["type"] == "text"
    assert sanitized[1]["content"][0]["text"] == "This is normal content"


def test_sanitize_conversation_history_preserves_mutable_thinking_blocks(llm):
    """Test that mutable thinking blocks are preserved."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Normal content"
                },
                {
                    "type": "thinking",
                    "content": "Mutable thinking",
                    "immutable": False
                },
                {
                    "type": "thinking",
                    "content": "No immutable flag - should be preserved"
                }
            ]
        }
    ]

    sanitized = llm._sanitize_conversation_history(messages)

    assert len(sanitized) == 1
    assert len(sanitized[0]["content"]) == 3

    # All content blocks should be preserved
    content = sanitized[0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "thinking"
    assert content[1]["immutable"] is False
    assert content[2]["type"] == "thinking"
    assert "immutable" not in content[2]  # No immutable flag means mutable


def test_sanitize_conversation_history_handles_string_content(llm):
    """Test that string content is preserved unchanged."""
    messages = [
        {
            "role": "user",
            "content": "Simple string content"
        },
        {
            "role": "assistant",
            "content": "Another string response"
        }
    ]

    sanitized = llm._sanitize_conversation_history(messages)

    assert sanitized == messages


def test_sanitize_conversation_history_handles_mixed_content_types(llm):
    """Test handling of mixed content types in messages."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Text content"
                },
                "Plain string in array",  # Non-dict content
                {
                    "type": "thinking",
                    "content": "Bad thinking",
                    "immutable": True
                },
                {
                    "type": "image",
                    "url": "http://example.com/image.jpg"
                }
            ]
        }
    ]

    sanitized = llm._sanitize_conversation_history(messages)

    content = sanitized[0]["content"]
    assert len(content) == 3  # Immutable thinking block should be removed
    assert content[0]["type"] == "text"
    assert content[1] == "Plain string in array"
    assert content[2]["type"] == "image"


def test_sanitize_conversation_history_handles_empty_messages(llm):
    """Test handling of empty message list."""
    messages = []
    sanitized = llm._sanitize_conversation_history(messages)
    assert sanitized == []


def test_sanitize_conversation_history_preserves_message_metadata(llm):
    """Test that non-content message fields are preserved."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "content": "Remove me",
                    "immutable": True
                }
            ],
            "name": "test-agent",
            "timestamp": "2024-01-01T00:00:00Z"
        }
    ]

    sanitized = llm._sanitize_conversation_history(messages)

    assert sanitized[0]["role"] == "assistant"
    assert sanitized[0]["name"] == "test-agent"
    assert sanitized[0]["timestamp"] == "2024-01-01T00:00:00Z"
    assert sanitized[0]["content"] == []  # Content removed but metadata preserved


@patch('strix.llm.llm.LLM._sanitize_conversation_history')
def test_prepare_messages_calls_sanitize_conversation_history(mock_sanitize, llm):
    """Test that _prepare_messages calls the sanitization method."""
    mock_sanitize.return_value = []

    # Mock the memory compressor to avoid complexity
    with patch.object(llm.memory_compressor, 'compress_history', return_value=[]):
        llm._prepare_messages([{"role": "user", "content": "test"}])

    # Verify sanitization was called
    mock_sanitize.assert_called_once()


def test_integration_thinking_block_api_error_scenario(llm):
    """Integration test simulating the API error scenario from thinking blocks."""
    # This simulates a conversation history that would cause API errors
    problematic_history = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "I found a potential vulnerability."
                },
                {
                    "type": "thinking",
                    "content": "Let me analyze this further...",
                    "immutable": True  # This would cause API errors if sent
                },
                {
                    "type": "redacted_thinking",
                    "content": "[REDACTED]",
                    "immutable": True
                }
            ]
        }
    ]

    # Mock the memory compressor to return the sanitized content
    with patch.object(llm.memory_compressor, 'compress_history') as mock_compress:
        mock_compress.return_value = []

        messages = llm._prepare_messages(problematic_history)

        # Verify the problematic history was sanitized before compression
        args_passed_to_compressor = mock_compress.call_args[0][0]

        # Should have one message with only the text content
        assert len(args_passed_to_compressor) == 1
        content = args_passed_to_compressor[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "I found a potential vulnerability."


def test_prepare_messages_preserves_original_conversation_history(llm):
    """Test that _prepare_messages does not modify the original conversation_history reference.

    This test verifies the fix for the thinking block modification bug where
    _prepare_messages was corrupting the original agent conversation state.
    """
    import copy

    # Create conversation history with thinking blocks (like agent state)
    original_conversation = [
        {
            "role": "user",
            "content": "Test for vulnerabilities"
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "I'll start by analyzing the target."
                },
                {
                    "type": "thinking",
                    "content": "I need to check the API endpoints...",
                    "immutable": True
                }
            ]
        },
        {
            "role": "user",
            "content": "Tool Results:\n\nPython session created successfully"
        }
    ]

    # Create a deep copy to compare against
    conversation_before = copy.deepcopy(original_conversation)

    # Mock memory compressor to avoid complexity
    with patch.object(llm.memory_compressor, 'compress_history') as mock_compress:
        mock_compress.return_value = [{"role": "user", "content": "compressed"}]

        # This call should NOT modify the original conversation_history
        prepared = llm._prepare_messages(original_conversation)

        # CRITICAL: Original conversation must be unchanged
        assert original_conversation == conversation_before, \
            "prepare_messages modified the original conversation_history reference"

        # Verify the conversation still has thinking blocks in original
        assistant_msg = original_conversation[1]
        thinking_blocks = [block for block in assistant_msg["content"]
                          if isinstance(block, dict) and block.get("type") == "thinking"]
        assert len(thinking_blocks) == 1, \
            "Original conversation should still contain thinking blocks"

        # Verify prepared messages exist and are different from original
        assert len(prepared) > 0, "Should have prepared messages"
        assert prepared != original_conversation, \
            "Prepared messages should be different from original"