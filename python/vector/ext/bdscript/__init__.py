"""BDScript for Vector: run Bot Designer for Discord (BDScript 2) and D.js-BDscript code on Vector.

    from vector.ext.bdscript import BDBot

    bot = BDBot(prefix="!")
    bot.variables({"money": 0})
    bot.command(trigger="!balance", code="$nomention You have $getUserVar[money] coins.")
    bot.run()
"""

from . import functions  # noqa: F401  (registers every function)
from .bot import BDBot, Command, CommandManager
from .context import Context
from .engine import BDScript, Result
from .interpreter import compile_code, run
from .parser import ParseError
from .registry import FUNCTIONS, BDScriptError, StopExecution, fn

Bot = BDBot  # D.js-BDscript name

__all__ = ("BDBot", "BDScript", "Result", "Bot", "Command", "CommandManager", "Context", "FUNCTIONS", "BDScriptError", "StopExecution",
           "ParseError", "compile_code", "fn", "run")
