"""Utility functions for the tools called by the LLM."""

import functools
import inspect
from typing import Callable, Optional


def trace_tool_call(func: Optional[Callable] = None) -> Callable:
    """
    Decorator that prints the function name and actual arguments when called.

    Usage:
        @trace_tool_call
        def my_function(arg1, arg2, kwarg1=None):
            return arg1 + arg2

    Args:
        func: The function to wrap

    Returns:
        Wrapped function that traces calls
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get the function signature
        sig = inspect.signature(func)

        # Bind the arguments to get a mapping of parameter names to values
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        # Format the arguments
        args_str = ", ".join(
            [f"{k}={repr(v)}" for k, v in bound_args.arguments.items()]
        )

        # Print the trace
        print(f"LLM Tool Call ::START:: {func.__name__}({args_str})")

        # Call the original function
        result = func(*args, **kwargs)

        # Optionally print when it ends (can comment out if too verbose)
        # print(f"LLM Tool Call ::END:: {func.__name__}")

        return result

    return wrapper


# def trace_tool_call():
#     """
#     Utility function that prints the function name and actual arguments
#     when called on the first line of any function

#     Returns:
#         tuple: (function_name, args_dict) containing the function name
#                and a dictionary of argument names to values
#     """
#     # Get the caller's frame (the function that called trace_function)
#     frame = sys._getframe(1)

#     # Get function name
#     function_name = frame.f_code.co_name

#     # Get the arguments info
#     arg_info = inspect.getargvalues(frame)

#     # Build a dictionary of argument names to values
#     args_dict = {}

#     # Get regular arguments (positional and keyword)
#     for arg_name in arg_info.args:
#         args_dict[arg_name] = arg_info.locals[arg_name]

#     # Get *args if present
#     if arg_info.varargs:
#         args_dict[f"*{arg_info.varargs}"] = arg_info.locals[arg_info.varargs]

#     # Get **kwargs if present
#     if arg_info.keywords:
#         args_dict[f"**{arg_info.keywords}"] = arg_info.locals[arg_info.keywords]

#     # Format the output
#     args_str = ", ".join([f"{k}={repr(v)}" for k, v in args_dict.items()])

#     print(f"LLM Tool Call ::START:: {function_name}({args_str})")

#     return function_name, args_dict
