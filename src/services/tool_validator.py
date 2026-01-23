import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

class ToolArgumentValidator:
    """
    Validates tool arguments against their defined schemas.
    Acts as a safety layer before tool execution.
    """

    @staticmethod
    def validate(
        tool_name: str,
        arguments: Dict[str, Any],
        available_tools: List[Dict[str, Any]]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate arguments for a specific tool.

        Args:
            tool_name: Name of the tool to validate
            arguments: The arguments dictionary to validate
            available_tools: List of tool definitions (OpenAI format)

        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        # 1. Find the tool definition
        tool_def = None
        for tool in available_tools:
            # Handle both nested 'function' format and flat format
            func = tool.get('function', tool)
            if func.get('name') == tool_name:
                tool_def = func
                break
        
        if not tool_def:
            return False, f"Tool '{tool_name}' is not in the list of available tools."

        # 2. Get parameter schema
        parameters = tool_def.get('parameters', {})
        properties = parameters.get('properties', {})
        required_params = parameters.get('required', [])

        # 3. Check required parameters
        for param in required_params:
            if param not in arguments:
                return False, f"Missing required parameter: '{param}'."

        # 4. Check parameter types (Basic checks)
        for arg_name, arg_value in arguments.items():
            if arg_name not in properties:
                # We typically allow extra args unless strict mode is on, 
                # but let's warn for hallucinated args
                continue 
            
            prop_type = properties[arg_name].get('type')
            if not prop_type:
                continue

            error = ToolArgumentValidator._check_type(arg_name, arg_value, prop_type)
            if error:
                return False, error

        return True, None

    @staticmethod
    def _check_type(arg_name: str, value: Any, expected_type: str) -> Optional[str]:
        """Check if value matches expected JSON schematype."""
        if expected_type == 'string':
            if not isinstance(value, str):
                return f"Parameter '{arg_name}' must be a string, got {type(value).__name__}."
        elif expected_type == 'integer':
            if not isinstance(value, int) or isinstance(value, bool): # bool is subclass of int in Python
                return f"Parameter '{arg_name}' must be an integer, got {type(value).__name__}."
        elif expected_type == 'number':
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return f"Parameter '{arg_name}' must be a number, got {type(value).__name__}."
        elif expected_type == 'boolean':
            if not isinstance(value, bool):
                return f"Parameter '{arg_name}' must be a boolean, got {type(value).__name__}."
        elif expected_type == 'array':
            if not isinstance(value, list):
                return f"Parameter '{arg_name}' must be a list/array, got {type(value).__name__}."
        elif expected_type == 'object':
            if not isinstance(value, dict):
                return f"Parameter '{arg_name}' must be a dictionary/object, got {type(value).__name__}."
        
        return None
