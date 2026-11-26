from pydantic import BaseModel, ConfigDict, Field, constr
from typing import Annotated


class WithdrawalCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    batch_id: str = Field(min_length=1, max_length=40)
    reason: Annotated[str, constr(strip_whitespace=True, min_length=4, max_length=500)]


class WithdrawalInfo(BaseModel):
    id: int
    dataset_id: int
    batch_id: str
    reason: str
    created_at: str
    affected_classes: list[str]
