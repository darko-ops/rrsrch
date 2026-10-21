"""The base for every request body: unknown fields are refused, naming them, rather than silently dropped, so a
misspelled or misplaced field is caught on the request that sent it."""
from pydantic import BaseModel, ConfigDict


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
