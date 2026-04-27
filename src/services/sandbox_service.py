import asyncio
import textwrap
import logging
import json
import math
import datetime
import re
import hashlib
import uuid
from typing import Any, Dict, Callable

logger = logging.getLogger(__name__)

class CodeSandboxService:
    """
    A service for executing LLM-generated Python code in a restricted environment.
    This enables "Code Mode" where the LLM orchestrates tools by writing code
    rather than returning multiple tool-call JSON objects.
    """
    
    def __init__(self):
        self.allowed_modules = {
            "json": json,
            "math": math,
            "datetime": datetime,
            "re": re,
            "hashlib": hashlib,
            "uuid": uuid
        }

        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            base_name = name.split('.')[0]
            if base_name in self.allowed_modules:
                return self.allowed_modules[base_name]
            raise ImportError(f"Import of module '{name}' is not allowed in the sandbox.")

        # Define the allowed builtins for the sandbox
        self.allowed_builtins = {
            "print": print,
            "__import__": safe_import,
            "len": len,
            "range": range,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "sum": sum,
            "min": min,
            "max": max,
            "enumerate": enumerate,
            "zip": zip,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
        }


    async def execute_script(self, code: str, call_tool: Callable) -> Dict[str, Any]:
        """
        Executes a Python script asynchronously.
        The script can use `await call_tool(tool_name, parameters)` to invoke tools.
        """
        # 1. Clean the code
        code = self._clean_code(code)
        
        # 2. Wrap the code in an async function so it can use 'await'
        wrapped_code = f"""
async def __sandbox_main(call_tool):
    output_log = []
    def sandbox_print(*args, **kwargs):
        output_log.append(" ".join(str(a) for a in args))
    
    # Expose custom print to user code
    print = sandbox_print
    result = None
        
{textwrap.indent(code, '    ')}

    return result, output_log
"""
        
        # 3. Setup the restricted globals
        sandbox_globals = {
            "__builtins__": self.allowed_builtins,
            # We don't provide imports like os or sys
        }
        sandbox_globals.update(self.allowed_modules)
        
        sandbox_locals = {}
        
        try:
            # 4. Compile and execute the definition
            exec(wrapped_code, sandbox_globals, sandbox_locals)
            
            # 5. Extract the generated function
            main_func = sandbox_locals.get("__sandbox_main")
            if not main_func:
                raise ValueError("Failed to compile sandbox function")
                
            # 6. Run the function with a timeout
            # We enforce a timeout to prevent infinite loops
            script_result, output_log = await asyncio.wait_for(main_func(call_tool), timeout=30.0)
            
            return {
                "success": True,
                "result": script_result,
                "output_log": output_log,
                "error": None
            }
            
        except asyncio.TimeoutError:
            logger.error("Sandbox execution timed out")
            return {
                "success": False,
                "result": None,
                "error": "Execution timed out after 30 seconds. You may have created an infinite loop."
            }
        except Exception as e:
            logger.error(f"Sandbox execution error: {e}")
            return {
                "success": False,
                "result": None,
                "error": f"Execution error: {str(e)}"
            }

    def _clean_code(self, code: str) -> str:
        """Removes markdown formatting if present."""
        code = code.strip()
        if code.startswith("```python"):
            code = code[9:]
        elif code.startswith("```"):
            code = code[3:]
            
        if code.endswith("```"):
            code = code[:-3]
            
        return code.strip()
