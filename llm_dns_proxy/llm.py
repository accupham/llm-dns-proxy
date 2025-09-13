"""
LLM integration using OpenAI API.
"""

import os
from typing import Optional
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

    async def process_message(self, message: str, system_prompt: str = None) -> str:
        """
        Process a message through the LLM and return the response.
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error processing message: {str(e)}"

    def process_message_sync(self, message: str, system_prompt: str = None) -> str:
        """
        Synchronous version of process_message.
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error processing message: {str(e)}"