"""
MCP Client Service to connect to external MCP servers (HTTP/WS/STDIO) and
expose their tools within Mini-Hub.
"""

import asyncio
import json
import logging
import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


class McpClientService:
    """Lightweight client for external MCP servers.

    Current implementation focuses on HTTP(S) integration by calling
    remote endpoints compatible with Mini-Hub's `/mcp/tools` and `/mcp/call`.

    Structure of `connection.config` expected:
    - transport: "http" | "ws" | "stdio" (http supported; ws/stdio placeholders)
    - url: base URL for HTTP/WS (e.g., https://remote.example.com/mcp)
    - headers: optional dict of headers
    - apiKey: optional token used to build Authorization header when headers absent
    - namespace: string prefix to namespace tools locally (e.g., "acme_")
    - timeoutMs: int (default 15000)
    - maxRetries: int (default 0)
    """

    def __init__(self) -> None:
        self._tools_cache: Dict[int, Tuple[List[Dict[str, Any]], float]] = {}
        self._cache_ttl_seconds: int = 60

    def _build_headers(self, config: Dict[str, Any]) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        user_headers = config.get("headers") or {}
        headers.update({k: str(v) for k, v in user_headers.items()})
        api_key = config.get("apiKey") or config.get("api_key")
        if api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _get_timeout(self, config: Dict[str, Any]) -> aiohttp.ClientTimeout:
        timeout_ms = int(config.get("timeoutMs", 15000))
        return aiohttp.ClientTimeout(total=max(1, timeout_ms) / 1000.0)

    async def _http_list_tools(self, base_url: str, headers: Dict[str, str], timeout: aiohttp.ClientTimeout) -> List[Dict[str, Any]]:
        url = base_url.rstrip("/") + "/tools"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"List tools failed {resp.status}: {text}")
                data = await resp.json()
        # Support both Mini-Hub shape {success, data: {tools: []}} and plain list
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict) and "tools" in data["data"]:
            return list(data["data"]["tools"]) or []
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "tools" in data:
            return list(data["tools"]) or []
        # Fallback: try mcp.server list_tools schema [{name, description, inputSchema}]
        return []

    async def _http_call_tool(self, base_url: str, headers: Dict[str, str], timeout: aiohttp.ClientTimeout, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        url = base_url.rstrip("/") + "/call"
        payload = {"name": name, "arguments": arguments or {}}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=json.dumps(payload)) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"Call tool failed {resp.status}: {text}")
                try:
                    data = json.loads(text)
                except Exception:
                    # Some servers might stream or return text; bubble up
                    return {"success": True, "raw": text}
        return data if isinstance(data, dict) else {"success": True, "data": data}

    # =============================
    # STDIO helpers
    # =============================

    async def _create_stdio_process(self, command: str, cwd: Optional[str], env: Optional[Dict[str, Any]]):
        logger.info(f"[DEBUG] Creating STDIO process with command: {command}")
        logger.info(f"[DEBUG] Working directory: {cwd}")
        logger.info(f"[DEBUG] Environment variables provided: {list(env.keys()) if env else 'None'}")
        
        merged_env = os.environ.copy()
        if env and isinstance(env, dict):
            for k, v in env.items():
                merged_env[str(k)] = str(v)
                logger.debug(f"[DEBUG] Setting env var: {k}={v[:20]}..." if len(str(v)) > 20 else f"[DEBUG] Setting env var: {k}={v}")

        logger.info(f"[DEBUG] Total environment variables: {len(merged_env)}")
        logger.info(f"[DEBUG] Attempting to start subprocess...")

        try:
            # Use shell for complex commands to support quoted paths, especially on Windows
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or None,
                env=merged_env,
            )
            logger.info(f"[DEBUG] Successfully created subprocess with PID: {process.pid}")
            
            # Give the process a moment to start and check if it's still running
            await asyncio.sleep(0.1)
            if process.returncode is not None:
                logger.error(f"[DEBUG] Process exited immediately with return code: {process.returncode}")
                # Try to read any error output
                try:
                    stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=1.0)
                    if stderr_data:
                        stderr_text = stderr_data.decode("utf-8", errors="replace")
                        logger.error(f"[DEBUG] Process stderr on exit: '{stderr_text}'")
                except Exception as e:
                    logger.warning(f"[DEBUG] Could not read stderr after process exit: {e}")
            else:
                logger.info("[DEBUG] Process is running successfully")
            
            return process
        except Exception as e:
            logger.error(f"[DEBUG] Failed to create subprocess: {type(e).__name__}: {e}")
            raise

    async def _stdio_jsonrpc_request(self, command: str, cwd: Optional[str], env: Optional[Dict[str, Any]], method: str, params: Dict[str, Any], timeout_ms: int) -> Dict[str, Any]:
        """Send a single JSON-RPC 2.0 request over stdio and return the parsed result.

        We assume line-delimited JSON frames for simplicity. Many MCP servers also support
        JSON-RPC over stdio. If this fails, callers should try a fallback.
        """
        logger.info(f"[DEBUG] Starting JSON-RPC request with method: {method}")
        proc = await self._create_stdio_process(command, cwd, env)
        try:
            request_obj = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            data = (json.dumps(request_obj) + "\n").encode("utf-8")
            logger.info(f"[DEBUG] Sending JSON-RPC request: {json.dumps(request_obj)}")
            logger.info(f"[DEBUG] Request data size: {len(data)} bytes")
            
            assert proc.stdin is not None and proc.stdout is not None
            logger.info("[DEBUG] Writing data to subprocess stdin...")
            proc.stdin.write(data)
            await proc.stdin.drain()
            logger.info("[DEBUG] Data sent successfully, waiting for response...")

            # Read one line as response
            timeout_s = max(1, timeout_ms) / 1000.0
            logger.info(f"[DEBUG] Waiting for response with timeout: {timeout_s}s")
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_s)
            logger.info(f"[DEBUG] Raw response line: {repr(line)}")
            
            text = line.decode("utf-8", errors="replace").strip()
            logger.info(f"[DEBUG] Decoded response text: '{text}' (length: {len(text)})")
            
            if not text:
                logger.warning("[DEBUG] Empty response, trying to read more...")
                # Try read remaining output quickly
                try:
                    remainder = await asyncio.wait_for(proc.stdout.readuntil(b"\n"), timeout=0.5)
                    logger.info(f"[DEBUG] Additional response data: {repr(remainder)}")
                    text = remainder.decode("utf-8", errors="replace").strip()
                    logger.info(f"[DEBUG] Combined response text: '{text}'")
                except Exception as read_error:
                    logger.warning(f"[DEBUG] Could not read additional data: {read_error}")
                    
            # Also check stderr for any error messages
            try:
                stderr_data = await asyncio.wait_for(proc.stderr.read(1024), timeout=0.1)
                if stderr_data:
                    stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                    logger.error(f"[DEBUG] Subprocess stderr: '{stderr_text}'")
            except Exception:
                pass  # No stderr or timeout
                
            logger.info("[DEBUG] Attempting to parse JSON response...")
            try:
                resp = json.loads(text)
                logger.info(f"[DEBUG] Successfully parsed JSON: {resp}")
            except Exception as parse_error:
                logger.error(f"[DEBUG] Initial JSON parse failed: {parse_error}")
                logger.error(f"[DEBUG] Failed text: '{text}'")
                logger.info("[DEBUG] Trying to read more lines for JSON response...")
                
                # If server prints non-JSON logs first, try to read more lines up to a few attempts
                for attempt in range(5):
                    logger.info(f"[DEBUG] Attempt {attempt + 1}/5 to read next line...")
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
                        if not line:
                            logger.warning(f"[DEBUG] No more data on attempt {attempt + 1}")
                            break
                        logger.info(f"[DEBUG] Attempt {attempt + 1} raw line: {repr(line)}")
                        text = line.decode("utf-8", errors="replace").strip()
                        logger.info(f"[DEBUG] Attempt {attempt + 1} decoded: '{text}'")
                        try:
                            resp = json.loads(text)
                            logger.info(f"[DEBUG] Successfully parsed JSON on attempt {attempt + 1}: {resp}")
                            break
                        except Exception as retry_parse_error:
                            logger.warning(f"[DEBUG] Attempt {attempt + 1} parse failed: {retry_parse_error}")
                            continue
                    except asyncio.TimeoutError:
                        logger.warning(f"[DEBUG] Timeout on attempt {attempt + 1}")
                        continue
                else:
                    logger.error(f"[DEBUG] All parse attempts failed. Final text: '{text[:200]}'")
                    raise RuntimeError(f"STDIO response not JSON: {text[:200]}")

            if isinstance(resp, dict):
                if "result" in resp:
                    return resp["result"]
                return resp
            return {"success": True, "data": resp}
        finally:
            # Best-effort terminate process
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    async def _stdio_jsonl_request(self, command: str, cwd: Optional[str], env: Optional[Dict[str, Any]], payload: Dict[str, Any], timeout_ms: int) -> Dict[str, Any]:
        """Send a single JSON line request like {action: 'list_tools'} and parse one-line JSON response."""
        logger.info("[DEBUG] Starting JSONL request...")
        logger.info(f"[DEBUG] JSONL payload: {payload}")
        proc = await self._create_stdio_process(command, cwd, env)
        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
            logger.info(f"[DEBUG] JSONL request data: {json.dumps(payload)}")
            logger.info(f"[DEBUG] JSONL data size: {len(data)} bytes")
            
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(data)
            await proc.stdin.drain()
            logger.info("[DEBUG] JSONL request sent successfully")

            timeout_s = max(1, timeout_ms) / 1000.0
            logger.info(f"[DEBUG] JSONL waiting for response with timeout: {timeout_s}s")
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_s)
            logger.info(f"[DEBUG] JSONL raw response: {repr(line)}")
            
            text = line.decode("utf-8", errors="replace").strip()
            logger.info(f"[DEBUG] JSONL decoded text: '{text}' (length: {len(text)})")
            
            if not text:
                logger.warning("[DEBUG] Empty JSONL response, checking stderr...")
                try:
                    stderr_data = await asyncio.wait_for(proc.stderr.read(1024), timeout=0.5)
                    if stderr_data:
                        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                        logger.error(f"[DEBUG] JSONL subprocess stderr: '{stderr_text}'")
                except Exception:
                    logger.warning("[DEBUG] No stderr data available")
                raise ValueError("Empty JSONL response from MCP server")
            
            try:
                resp = json.loads(text)
                logger.info(f"[DEBUG] JSONL successfully parsed: {resp}")
                result = resp if isinstance(resp, dict) else {"data": resp}
                logger.info(f"[DEBUG] JSONL final result: {result}")
                return result
            except json.JSONDecodeError as parse_error:
                logger.error(f"[DEBUG] JSONL JSON parse error: {parse_error}")
                logger.error(f"[DEBUG] JSONL failed text: '{text}'")
                raise ValueError(f"Invalid JSONL response: {parse_error}")
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    async def get_tools_for_connection(self, connection) -> List[Dict[str, Any]]:
        """Fetch remote tools for a given `Connection` record.

        Uses an in-memory cache for a short TTL to avoid frequent network calls.
        """
        now = asyncio.get_event_loop().time()
        cached = self._tools_cache.get(connection.id)
        if cached and (now - cached[1] < self._cache_ttl_seconds):
            return cached[0]

        cfg = connection.config or {}
        transport = (cfg.get("transport") or "http").lower()

        if transport == "http":
            base_url = cfg.get("url")
            if not base_url:
                raise ValueError("mcp_remote config requires 'url' for http transport")
            headers = self._build_headers(cfg)
            timeout = self._get_timeout(cfg)
            tools = await self._http_list_tools(base_url, headers, timeout)
        elif transport in ("ws", "wss"):
            # Placeholder for future WS transport
            raise NotImplementedError("WebSocket transport for MCP is not implemented yet")
        elif transport == "stdio":
            command = cfg.get("command")
            if not command:
                raise ValueError("mcp_remote config requires 'command' for stdio transport")
            cwd = cfg.get("cwd")
            env = cfg.get("env") or {}
            timeout_ms = int(cfg.get("timeoutMs", 15000))

            # Try JSON-RPC method names first, then fallback to simple action
            result: Any = None
            try:
                result = await self._stdio_jsonrpc_request(command, cwd, env, "tools/list", {}, timeout_ms)
            except Exception:
                try:
                    result = await self._stdio_jsonrpc_request(command, cwd, env, "list_tools", {}, timeout_ms)
                except Exception:
                    result = await self._stdio_jsonl_request(command, cwd, env, {"action": "list_tools"}, timeout_ms)

            # Normalize tools
            if isinstance(result, dict):
                if "tools" in result and isinstance(result["tools"], list):
                    tools = result["tools"]
                elif "data" in result and isinstance(result["data"], list):
                    tools = result["data"]
                else:
                    tools = result if isinstance(result, list) else []
            elif isinstance(result, list):
                tools = result
            else:
                tools = []
        else:
            raise ValueError(f"Unsupported MCP transport: {transport}")

        # Cache and return
        self._tools_cache[connection.id] = (tools, now)
        return tools

    async def call_tool(self, connection, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        cfg = connection.config or {}
        transport = (cfg.get("transport") or "http").lower()

        if transport == "http":
            base_url = cfg.get("url")
            if not base_url:
                raise ValueError("mcp_remote config requires 'url' for http transport")
            headers = self._build_headers(cfg)
            timeout = self._get_timeout(cfg)
            return await self._http_call_tool(base_url, headers, timeout, name, arguments)
        elif transport in ("ws", "wss"):
            raise NotImplementedError("WebSocket transport for MCP is not implemented yet")
        elif transport == "stdio":
            command = cfg.get("command")
            if not command:
                raise ValueError("mcp_remote config requires 'command' for stdio transport")
            cwd = cfg.get("cwd")
            env = cfg.get("env") or {}
            timeout_ms = int(cfg.get("timeoutMs", 15000))

            # Try JSON-RPC style first
            try:
                result = await self._stdio_jsonrpc_request(
                    command, cwd, env,
                    "tools/call",
                    {"name": name, "arguments": arguments or {}},
                    timeout_ms,
                )
            except Exception:
                try:
                    result = await self._stdio_jsonrpc_request(
                        command, cwd, env,
                        "call_tool",
                        {"name": name, "arguments": arguments or {}},
                        timeout_ms,
                    )
                except Exception:
                    result = await self._stdio_jsonl_request(
                        command, cwd, env,
                        {"action": "call_tool", "name": name, "arguments": arguments or {}},
                        timeout_ms,
                    )

            return result if isinstance(result, dict) else {"success": True, "data": result}
        else:
            raise ValueError(f"Unsupported MCP transport: {transport}")

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a remote MCP connection by listing tools."""
        try:
            transport = (config.get("transport") or "http").lower()
            logger.info(f"[DEBUG] Testing MCP connection with transport: {transport}")
            
            if transport == "stdio":
                command = config.get("command")
                if not command:
                    logger.error("[DEBUG] Missing 'command' in config for stdio transport")
                    return {"success": False, "error": "Missing 'command' in config for stdio transport"}
                    
                cwd = config.get("cwd")
                env = config.get("env") or {}
                timeout_ms = int(config.get("timeoutMs", 15000))
                
                logger.info(f"[DEBUG] STDIO test - Command: {command}")
                logger.info(f"[DEBUG] STDIO test - Working directory: {cwd}")
                logger.info(f"[DEBUG] STDIO test - Timeout: {timeout_ms}ms")
                logger.info(f"[DEBUG] STDIO test - Environment vars: {list(env.keys())}")
                
                try:
                    logger.info("[DEBUG] Attempting first JSON-RPC request: tools/list")
                    result = await self._stdio_jsonrpc_request(command, cwd, env, "tools/list", {}, timeout_ms)
                    logger.info("[DEBUG] First JSON-RPC request succeeded")
                except Exception as e1:
                    logger.warning(f"[DEBUG] First JSON-RPC request failed: {e1}")
                    try:
                        logger.info("[DEBUG] Attempting second JSON-RPC request: list_tools")
                        result = await self._stdio_jsonrpc_request(command, cwd, env, "list_tools", {}, timeout_ms)
                        logger.info("[DEBUG] Second JSON-RPC request succeeded")
                    except Exception as e2:
                        logger.warning(f"[DEBUG] Second JSON-RPC request failed: {e2}")
                        logger.info("[DEBUG] Attempting JSONL request")
                        result = await self._stdio_jsonl_request(command, cwd, env, {"action": "list_tools"}, timeout_ms)
                        logger.info("[DEBUG] JSONL request succeeded")
                        
                tools = []
                if isinstance(result, dict) and isinstance(result.get("tools"), list):
                    tools = result["tools"]
                elif isinstance(result, list):
                    tools = result
                    
                logger.info(f"[DEBUG] Test connection successful, found {len(tools)} tools")
                return {"success": True, "tools_found": len(tools)}
                
            if transport not in ("http", "https"):
                logger.error(f"[DEBUG] Unsupported transport for test: {transport}")
                return {"success": False, "error": f"Unsupported transport for test: {transport}"}
                
            base_url = config.get("url")
            if not base_url:
                logger.error("[DEBUG] Missing 'url' in config for HTTP transport")
                return {"success": False, "error": "Missing 'url' in config"}
                
            headers = self._build_headers(config)
            timeout = self._get_timeout(config)
            logger.info(f"[DEBUG] HTTP test - URL: {base_url}")
            tools = await self._http_list_tools(base_url, headers, timeout)
            logger.info(f"[DEBUG] HTTP test successful, found {len(tools)} tools")
            return {"success": True, "tools_found": len(tools)}
            
        except Exception as e:
            logger.error(f"[DEBUG] MCP remote test failed with exception: {type(e).__name__}: {e}")
            return {"success": False, "error": str(e)}


# Global instance
mcp_client_service = McpClientService()


