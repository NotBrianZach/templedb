#!/usr/bin/env python3
"""
Claude Code Interaction Capture for Vibe Sessions

Monitors Claude Code I/O and logs all interactions to the vibe server.
Can run as a wrapper around Claude Code or monitor an existing session.
"""
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

import requests


class ClaudeInteractionCapture:
    """Captures and logs Claude Code interactions to vibe server"""

    def __init__(self, session_id: int, port: int = 8765):
        self.session_id = session_id
        self.port = port
        self.base_url = f"http://localhost:{port}"
        self.last_prompt_id: Optional[int] = None
        self.turn_in_progress = False
        self.response_start_time = None

    def log_interaction(self, interaction_type: str, role: str, content: str, **kwargs):
        """Log an interaction to the vibe server"""
        try:
            data = {
                'session_id': self.session_id,
                'interaction_type': interaction_type,
                'role': role,
                'content': content,
                **kwargs
            }

            response = requests.post(
                f"{self.base_url}/api/vibe/interaction",
                json=data,
                timeout=5
            )
            response.raise_for_status()
            result = response.json()

            print(f"[VIBE] Logged {interaction_type} (ID: {result['interaction_id']})",
                  file=sys.stderr)

            return result['interaction_id']

        except Exception as e:
            print(f"[VIBE] Error logging interaction: {e}", file=sys.stderr)
            return None

    def create_pair(self, prompt_id: int, response_id: int):
        """Create a prompt-response pair"""
        try:
            data = {
                'session_id': self.session_id,
                'prompt_interaction_id': prompt_id,
                'response_interaction_id': response_id
            }

            response = requests.post(
                f"{self.base_url}/api/vibe/interaction/pair",
                json=data,
                timeout=5
            )
            response.raise_for_status()

            print(f"[VIBE] Created interaction pair", file=sys.stderr)

        except Exception as e:
            print(f"[VIBE] Error creating pair: {e}", file=sys.stderr)

    def parse_tool_use(self, content: str) -> List[Dict]:
        """Parse tool uses from Claude response"""
        tools = []

        # Pattern for function calls
        tool_pattern = r'<invoke name="([^"]+)">(.*?)</invoke>'
        matches = re.findall(tool_pattern, content, re.DOTALL)

        for tool_name, params_xml in matches:
            # Extract parameters
            params = {}
            param_pattern = r'<parameter name="([^"]+)">(.*?)</parameter>'
            param_matches = re.findall(param_pattern, params_xml, re.DOTALL)

            for param_name, param_value in param_matches:
                params[param_name] = param_value.strip()

            tools.append({
                'name': tool_name,
                'params': params
            })

        return tools

    def extract_files_mentioned(self, content: str) -> List[str]:
        """Extract file paths mentioned in content"""
        # Look for common file path patterns
        file_patterns = [
            r'`([^`]+\.\w+)`',  # Backtick-quoted files
            r'"([^"]+\.\w+)"',  # Quote-quoted files
            r"'([^']+\.\w+)'",  # Single-quoted files
            r'\b([a-zA-Z0-9_./\-]+\.(?:py|js|ts|jsx|tsx|json|md|sql|sh|yaml|yml|toml|txt))\b'
        ]

        files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, content)
            files.update(matches)

        return list(files)

    def process_user_prompt(self, prompt: str):
        """Process a user prompt"""
        self.response_start_time = time.time()

        # Log the prompt
        files_mentioned = self.extract_files_mentioned(prompt)

        self.last_prompt_id = self.log_interaction(
            interaction_type='user_prompt',
            role='user',
            content=prompt,
            related_files=files_mentioned if files_mentioned else None
        )

        self.turn_in_progress = True

    def process_assistant_response(self, response: str, latency_ms: Optional[int] = None):
        """Process an assistant response"""
        if latency_ms is None and self.response_start_time:
            latency_ms = int((time.time() - self.response_start_time) * 1000)

        # Parse tool uses
        tools = self.parse_tool_use(response)
        files_mentioned = self.extract_files_mentioned(response)

        # Log the response
        response_id = self.log_interaction(
            interaction_type='assistant_response',
            role='assistant',
            content=response,
            latency_ms=latency_ms,
            related_files=files_mentioned if files_mentioned else None
        )

        # Log tool uses separately
        for tool in tools:
            self.log_interaction(
                interaction_type='tool_use',
                role='assistant',
                content=f"Tool: {tool['name']}",
                tool_name=tool['name'],
                tool_params=tool['params']
            )

        # Create pair if we have both prompt and response
        if self.last_prompt_id and response_id:
            self.create_pair(self.last_prompt_id, response_id)

        self.turn_in_progress = False
        self.response_start_time = None

    def process_tool_result(self, tool_name: str, result: str, success: bool = True):
        """Process a tool execution result"""
        self.log_interaction(
            interaction_type='tool_result',
            role='system',
            content=result,
            tool_name=tool_name,
            tool_success=success
        )


class ClaudeCodeMonitor:
    """Monitors Claude Code session and captures interactions"""

    def __init__(self, session_id: int, port: int = 8765, log_file: Optional[Path] = None):
        self.capture = ClaudeInteractionCapture(session_id, port)
        self.log_file = log_file

    def monitor_file(self, file_path: Path):
        """Monitor a log file for Claude Code output"""
        print(f"[VIBE] Monitoring {file_path} for Claude Code interactions...",
              file=sys.stderr)

        # Follow the file (like tail -f)
        with open(file_path, 'r') as f:
            # Seek to end
            f.seek(0, 2)

            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                # Parse and process line
                self.process_line(line)

    def process_line(self, line: str):
        """Process a single line from the log"""
        # This is a placeholder - actual implementation would need to
        # parse the Claude Code output format
        pass


class ClaudeCodeWrapper:
    """Wrapper around Claude Code that captures I/O"""

    def __init__(self, session_id: int, port: int = 8765):
        self.capture = ClaudeInteractionCapture(session_id, port)
        self.prompt_buffer = []
        self.response_buffer = []
        self.in_response = False

    async def run(self, claude_cmd: List[str]):
        """Run Claude Code with I/O capture"""
        print(f"[VIBE] Starting Claude Code with interaction capture...",
              file=sys.stderr)

        # Start Claude Code as subprocess
        process = await asyncio.create_subprocess_exec(
            *claude_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Monitor stdout
        async def monitor_output():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break

                line_str = line.decode('utf-8')
                sys.stdout.write(line_str)
                sys.stdout.flush()

                # Detect prompts and responses
                # This is simplified - real implementation would need better detection
                if line_str.strip().startswith('>'):  # User prompt indicator
                    if self.response_buffer:
                        response = ''.join(self.response_buffer)
                        self.capture.process_assistant_response(response)
                        self.response_buffer = []
                    self.in_response = False
                else:
                    if not self.in_response:
                        self.in_response = True
                        if self.prompt_buffer:
                            prompt = ''.join(self.prompt_buffer)
                            self.capture.process_user_prompt(prompt)
                            self.prompt_buffer = []

                    self.response_buffer.append(line_str)

        # Start output monitor
        asyncio.create_task(monitor_output())

        # Wait for process
        await process.wait()
        return process.returncode


# CLI Interface
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Capture Claude Code interactions for vibe sessions'
    )
    parser.add_argument('--session-id', type=int, required=True,
                       help='Vibe session ID')
    parser.add_argument('--port', type=int, default=8765,
                       help='Vibe server port')
    parser.add_argument('--mode', choices=['wrapper', 'monitor', 'test'],
                       default='test', help='Capture mode')
    parser.add_argument('--log-file', type=Path,
                       help='Log file to monitor (for monitor mode)')
    parser.add_argument('claude_args', nargs='*',
                       help='Arguments to pass to Claude Code (for wrapper mode)')

    args = parser.parse_args()

    if args.mode == 'wrapper':
        # Wrapper mode - run Claude Code with I/O capture
        wrapper = ClaudeCodeWrapper(args.session_id, args.port)
        asyncio.run(wrapper.run(args.claude_args))

    elif args.mode == 'monitor':
        # Monitor mode - watch a log file
        if not args.log_file:
            print("Error: --log-file required for monitor mode", file=sys.stderr)
            return 1

        monitor = ClaudeCodeMonitor(args.session_id, args.port, args.log_file)
        monitor.monitor_file(args.log_file)

    elif args.mode == 'test':
        # Test mode - send some test interactions
        print("[VIBE] Testing interaction capture...", file=sys.stderr)

        capture = ClaudeInteractionCapture(args.session_id, args.port)

        # Test prompt
        capture.process_user_prompt("Can you help me implement a login feature?")
        time.sleep(0.5)

        # Test response
        response = """I'd be happy to help! Let me create a basic login feature.

```python
def login(username: str, password: str) -> bool:
    # Hash password and check against database
    return check_credentials(username, password)
```

Let me also add proper error handling."""

        capture.process_assistant_response(response)

        print("[VIBE] Test interactions sent!", file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
