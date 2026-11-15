from pydantic import BaseModel, Field
class ReviewInput(BaseModel):
    decision: str = Field(pattern='^(release|keep)$')
    note: str = Field(min_length=2, max_length=500)
