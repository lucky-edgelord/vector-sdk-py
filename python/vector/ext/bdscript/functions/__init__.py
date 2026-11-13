"""All BDScript functions. Importing this package registers them."""

from . import (botinfo, components, core, embeds, extra, jsonhttp, mathfn, messages, people, server, text,  # noqa: F401
               timefn, variables, vectorfns)

extra.register_uncached()
vectorfns.register_aliases()
