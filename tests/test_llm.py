"""
Tests for LLM integration.
"""

import pytest
from unittest.mock import Mock, patch
from llm_dns_proxy.llm import LLMProcessor


class TestLLMProcessor:
    def test_init_with_api_key(self):
        processor = LLMProcessor(api_key="test-key")
        assert processor.api_key == "test-key"

    def test_init_with_custom_base_url(self):
        processor = LLMProcessor(api_key="test-key", base_url="http://localhost:8080/v1")
        assert processor.api_key == "test-key"
        assert processor.base_url == "http://localhost:8080/v1"

    def test_init_with_custom_model(self):
        processor = LLMProcessor(api_key="test-key", model="custom-model")
        assert processor.api_key == "test-key"
        assert processor.model == "custom-model"

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'env-key'})
    def test_init_from_env(self):
        processor = LLMProcessor()
        assert processor.api_key == "env-key"

    @patch.dict('os.environ', {
        'OPENAI_API_KEY': 'env-key',
        'OPENAI_BASE_URL': 'http://localhost:8080/v1',
        'OPENAI_MODEL': 'env-model'
    })
    def test_init_from_env_with_base_url_and_model(self):
        processor = LLMProcessor()
        assert processor.api_key == "env-key"
        assert processor.base_url == "http://localhost:8080/v1"
        assert processor.model == "env-model"

    @patch.dict('os.environ', {
        'OPENAI_API_KEY': 'env-key',
        'OPENAI_BASE_URL': 'http://localhost:8080/v1',
        'OPENAI_MODEL': 'env-model'
    })
    def test_parameter_overrides_env(self):
        processor = LLMProcessor(
            base_url="http://custom:9000/v1",
            model="custom-model"
        )
        assert processor.api_key == "env-key"  # From env
        assert processor.base_url == "http://custom:9000/v1"  # From parameter
        assert processor.model == "custom-model"  # From parameter

    def test_init_no_api_key(self):
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="OpenAI API key must be provided"):
                LLMProcessor()

    @patch('llm_dns_proxy.llm.OpenAI')
    def test_process_message_sync_success(self, mock_openai):
        mock_choice = Mock()
        mock_choice.message.content = "Test response"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        processor = LLMProcessor(api_key="test-key")
        result = processor.process_message_sync("Test message")

        assert result == "Test response"
        mock_openai.return_value.chat.completions.create.assert_called_once()

    @patch('llm_dns_proxy.llm.OpenAI')
    def test_process_message_sync_with_system_prompt(self, mock_openai):
        mock_choice = Mock()
        mock_choice.message.content = "Test response"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        processor = LLMProcessor(api_key="test-key")
        result = processor.process_message_sync("Test message", "System prompt")

        assert result == "Test response"

        call_args = mock_openai.return_value.chat.completions.create.call_args
        messages = call_args[1]['messages']
        assert len(messages) == 2
        assert messages[0]['role'] == 'system'
        assert messages[0]['content'] == 'System prompt'
        assert messages[1]['role'] == 'user'
        assert messages[1]['content'] == 'Test message'

    @patch('llm_dns_proxy.llm.OpenAI')
    def test_process_message_sync_error(self, mock_openai):
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API Error")

        processor = LLMProcessor(api_key="test-key")
        result = processor.process_message_sync("Test message")

        assert "Error processing message: API Error" in result

    @patch('llm_dns_proxy.llm.OpenAI')
    @pytest.mark.asyncio
    async def test_process_message_async_success(self, mock_openai):
        mock_choice = Mock()
        mock_choice.message.content = "Async response"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        processor = LLMProcessor(api_key="test-key")
        result = await processor.process_message("Test message")

        assert result == "Async response"

    @patch.dict('os.environ', {'OPENAI_MODEL': 'gpt-4'})
    @patch('llm_dns_proxy.llm.OpenAI')
    def test_custom_model_from_env(self, mock_openai):
        mock_choice = Mock()
        mock_choice.message.content = "Response"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        processor = LLMProcessor(api_key="test-key")
        processor.process_message_sync("Test")

        call_args = mock_openai.return_value.chat.completions.create.call_args
        assert call_args[1]['model'] == 'gpt-4'