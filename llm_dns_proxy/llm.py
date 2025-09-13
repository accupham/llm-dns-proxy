import os, json
from typing import Optional, List, Dict, Any
from openai import OpenAI

class LLMProcessor:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY missing")

        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)

        # Optional Perplexity client
        self.perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        self.perplexity_client = None
        if self.perplexity_api_key:
            self.perplexity_client = OpenAI(
                api_key=self.perplexity_api_key,
                base_url="https://api.perplexity.ai"
            )

        self.tools = []
        if self.perplexity_client:
            self.tools.append({
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web using perplexity.ai for current information and real-time data",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"}
                        },
                        "required": ["query"]
                    }
                }
            })

    def _execute_tool(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args) if raw_args else {}
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Invalid tool arguments: {e}", "raw": raw_args})

        if name == "web_search":
            q = args.get("query", "")
            print(f"Executing web_search with query: {q}")
            return self.web_search(q)

        return json.dumps({"ok": False, "error": f"Unknown tool: {name}", "args": args})

    def process_message_sync(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1200,
        max_tool_iterations: int = 4
    ) -> str:
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        base_params = {
            "model": self.model,
            "temperature": 1.0 if self.model.startswith("gpt-5") else temperature,
            "max_completion_tokens": max_tokens,
        }

        tools_enabled_params = dict(base_params)
        if self.tools:
            tools_enabled_params["tools"] = self.tools
            tools_enabled_params["tool_choice"] = "auto"

        seen_calls = set()  # (name, canonical_args_json)

        try:
            # We alternate: (A) allow tools  -> (B) force synthesis (no tools)
            # Repeat until no tool calls or iteration cap.
            for _ in range(max_tool_iterations):
                # (A) Let the model decide if it wants a tool
                resp = self.client.chat.completions.create(messages=messages, **tools_enabled_params)
                choice = resp.choices[0]
                msg = choice.message
                tool_calls = getattr(msg, "tool_calls", None)

                if not tool_calls:
                    return msg.content or ""

                # Append assistant message with tool_calls (content can be "")
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in tool_calls
                    ]
                })

                # Execute each tool call
                duplicate = False
                for tc in tool_calls:
                    name = tc.function.name
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args_obj = json.loads(raw_args) if raw_args else {}
                    except Exception:
                        args_obj = {"_raw": raw_args}
                    canonical_args = json.dumps(args_obj, sort_keys=True)
                    key = (name, canonical_args)

                    if key in seen_calls:
                        duplicate = True
                        # Tell the model explicitly (in the tool channel) that this is a duplicate
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({
                                "ok": False,
                                "error": "duplicate_tool_call",
                                "message": "This exact tool+arguments already ran; not re-running.",
                                "function": name,
                                "arguments": args_obj
                            })
                        })
                        continue

                    seen_calls.add(key)

                    result = self._execute_tool(name, raw_args)
                    # Ensure result is a string; try to keep it structured
                    if not isinstance(result, str):
                        result = json.dumps(result)

                    # Keep the tool schema minimal: NO 'name' field here
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result
                    })

                # (B) Force a synthesis pass with tools disabled so the model must use results
                synth_params = dict(base_params)  # no tools / no tool_choice
                # Add a short nudge: many models terminate tool use sooner with this hint
                messages.append({
                    "role": "system",
                    "content": "You have received tool results above. Use them to answer. "
                               "Do not call the same tool with identical arguments again."
                })
                resp2 = self.client.chat.completions.create(messages=messages, **synth_params)
                msg2 = resp2.choices[0].message

                # If the model answered, we’re done.
                if not getattr(msg2, "tool_calls", None):
                    return msg2.content or ""

                # If it *still* tries to call tools in the synthesis pass, allow one more loop,
                # but the dedupe will block identical repeats.
                messages.append({
                    "role": "assistant",
                    "content": msg2.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in msg2.tool_calls
                    ]
                })
                # Loop continues, and we’ll run the new tool args (if different)

            return "Stopped after max tool iterations without a final answer."

        except Exception as e:
            return f"Error processing message: {e}"

    # --- Tools ---

    def web_search(self, query: str, model: str = "sonar-pro") -> str:
        if not self.perplexity_client:
            return json.dumps({"ok": False, "error": "PERPLEXITY_API_KEY not configured"})

        try:
            messages = [
                {"role": "system", "content": "You search the web and return concise, sourced summaries."},
                {"role": "user", "content": query}
            ]
            resp = self.perplexity_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=800,  # IMPORTANT: Chat Completions uses max_tokens
            )
            content = resp.choices[0].message.content or ""
            # Keep it structured so the model can plan
            return json.dumps({"ok": True, "query": query, "answer": content})
        except Exception as e:
            return json.dumps({"ok": False, "error": f"Perplexity error: {e}", "query": query})
