"""Reusable OpenAPI ``responses=`` fragments for route decorators.

Sonar's FastAPI rule wants every ``HTTPException`` a route can raise reflected
in that route's ``responses`` so it shows up in the generated OpenAPI schema.
Rather than repeat the same dict on every decorator, import the matching error
fragments here and merge them, e.g.::

    @router.post("/things", responses={**ERR_400, **ERR_404})

Each value is keyed by the HTTP status code (FastAPI's ``responses`` format).
"""

ERR_400 = {400: {"description": "Bad request — invalid or conflicting input"}}
ERR_401 = {401: {"description": "Unauthorized — authentication required"}}
ERR_403 = {403: {"description": "Forbidden — insufficient permissions"}}
ERR_404 = {404: {"description": "Not found"}}
ERR_409 = {409: {"description": "Conflict — resource already exists or is in use"}}
ERR_422 = {422: {"description": "Unprocessable entity"}}
ERR_500 = {500: {"description": "Internal server error"}}
