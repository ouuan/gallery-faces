from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

Key = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
Identifier = Annotated[int, Field(gt=0, le=9223372036854775807)]
TempPerson = Annotated[str, Field(pattern=r'^new:[A-Za-z0-9_-]{1,80}$')]
Person = Identifier | TempPerson
Box = tuple[float, float, float, float]
Attachment = Annotated[str, Field(pattern=r'^attachments/[A-Za-z0-9_-]{1,100}\.(jpg|jpeg|png|webp)$')]


class Suggestion(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: Key
    image_id: Identifier
    reason: str = Field(min_length=1, max_length=4000)
    confidence: Literal['low', 'medium', 'high'] | None = Field(default=None, description='Agent assessment of this suggestion, independent of face-match scores.')


class Match(Suggestion):
    kind: Literal['match']
    face_id: Identifier
    person_id: Person | None


class Remove(Suggestion):
    kind: Literal['remove_face']
    face_id: Identifier


class AddFace(Suggestion):
    kind: Literal['add_face']
    box: Box
    person_id: Person | None = None


class CreatePerson(Suggestion):
    kind: Literal['create_person']
    person_id: TempPerson
    name: str = Field(min_length=1, max_length=100, pattern=r'\S')
    group_ids: list[Identifier] = Field(default_factory=list, max_length=100, description='Existing person group IDs from this batch\'s groups.json.')
    new_groups: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r'\S')]] = Field(
        default_factory=list, max_length=100, description='Group names to create or reuse by exact name on acceptance.')


class LibraryReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    face_id: Identifier


class ExternalReference(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    attachment: Attachment
    source_url: HttpUrl | None = None
    box: Box | None = None


class AddReference(Suggestion):
    kind: Literal['add_reference']
    person_id: Person
    source: LibraryReference | ExternalReference


class Recycle(Suggestion):
    kind: Literal['recycle']


Operation = Annotated[Match | Remove | AddFace | CreatePerson | AddReference | Recycle, Field(discriminator='kind')]


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1]
    batch: str = Field(pattern=r'^[0-9a-f]{32}$')
    suggestions: list[Operation] = Field(max_length=5000)


def fits(box, width, height):
    left, top, wide, high = box
    return left >= 0 and top >= 0 and wide > 0 and high > 0 and left + wide <= width and top + high <= height
