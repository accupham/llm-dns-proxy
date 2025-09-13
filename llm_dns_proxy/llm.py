"""
LLM integration using OpenAI API.
"""

import os
from typing import Optional, List, Dict
from openai import OpenAI


class LLMProcessor:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key must be provided via parameter or OPENAI_API_KEY environment variable")

        self.base_url = base_url or os.getenv('OPENAI_BASE_URL')
        self.model = model or os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')

        # Create client with optional base_url for custom servers
        client_kwargs = {'api_key': self.api_key}
        if self.base_url:
            client_kwargs['base_url'] = self.base_url

        self.client = OpenAI(**client_kwargs)

    async def process_message(self, message: str, system_prompt: str = None,
                            conversation_history: List[Dict[str, str]] = None) -> str:
        """
        Process a message through the LLM and return the response with conversation history support.
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})

        try:
            # Determine the correct parameters based on model
            api_params = {}

            # Token limit parameter
            if 'gpt-4' in self.model.lower() or 'gpt-5' in self.model.lower():
                api_params['max_completion_tokens'] = 1000
            else:
                api_params['max_tokens'] = 1000

            # Temperature parameter - GPT-5 only supports default (1)
            if 'gpt-5' in self.model.lower():
                # GPT-5 only supports temperature=1 (default), so omit it
                pass
            else:
                api_params['temperature'] = 0.7

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **api_params
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error processing message: {str(e)}"

    def process_message_sync(self, message: str, system_prompt: str = None,
                           conversation_history: List[Dict[str, str]] = None) -> str:
        """
        Synchronous version of process_message with conversation history support.
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})

        try:
            # Determine the correct parameters based on model
            api_params = {}

            # Token limit parameter
            if 'gpt-4' in self.model.lower() or 'gpt-5' in self.model.lower():
                api_params['max_completion_tokens'] = 1000
            else:
                api_params['max_tokens'] = 1000

            # Temperature parameter - GPT-5 only supports default (1)
            if 'gpt-5' in self.model.lower():
                # GPT-5 only supports temperature=1 (default), so omit it
                pass
            else:
                api_params['temperature'] = 0.7

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **api_params
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error processing message: {str(e)}"