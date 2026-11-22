from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from .metadata import validate_url

Key = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
Identifier = Annotated[int, Field(gt=0, le=9223372036854775807)]
TempPerson = Annotated[str, Field(pattern=r'^new:[A-Za-z0-9_-]{1,80}$')]
Person = Identifier | TempPerson
Box = tuple[float, float, float, float]
Attachment = Annotated[str, Field(pattern=r'^attachments/[A-Za-z0-9_-]{1,100}\.(jpg|jpeg|png|webp)$')]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r'\S')]


class ReviewAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    platform: Literal['instagram', 'x']
    username: str = Field(min_length=1, max_length=100, pattern=r'^[\w.]+$')


class ReviewGroupName(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Name
    name_ja: Name | None = None


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
    name_ja: Name | None = None
    accounts: list[ReviewAccount] = Field(default_factory=list, max_length=100)
    group_ids: list[Identifier] = Field(default_factory=list, max_length=100, description='Existing person group IDs from this batch\'s groups.json.')
    new_groups: list[Name | ReviewGroupName] = Field(
        default_factory=list, max_length=100, description='Group names to create or reuse by exact name on acceptance.')


class PersonNameJa(Suggestion):
    kind: Literal['set_person_name_ja']
    person_id: Identifier
    name_ja: Name


class GroupNameJa(Suggestion):
    kind: Literal['set_group_name_ja']
    group_id: Identifier
    name_ja: Name


class AddPersonAccount(Suggestion):
    kind: Literal['add_person_account']
    person_id: Identifier
    account: ReviewAccount


class AddPersonGroup(Suggestion):
    kind: Literal['add_person_group']
    person_id: Identifier
    group_id: Identifier


class CorrectSource(Suggestion):
    kind: Literal['correct_source']
    post_id: Identifier
    field: Literal['author', 'author_name', 'published_at', 'url', 'post_text']
    value: Annotated[str, StringConstraints(min_length=1, max_length=16000, pattern=r'\S')] | None

    @model_validator(mode='after')
    def valid_source_value(self):
        if self.value is None:
            if self.field not in ('author_name', 'post_text'):
                raise ValueError('仅发布者名称和正文可以清空')
            return self
        if self.field == 'url' and not validate_url(self.value):
            raise ValueError('请输入受支持的平台链接')
        if self.field == 'published_at':
            date = datetime.fromisoformat(self.value)
            if date.tzinfo is None:
                raise ValueError('发布时间必须包含时区')
            try:
                self.value = date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            except OverflowError as error:
                raise ValueError('发布时间超出范围') from error
        return self


class ReviewOutcome(Suggestion):
    kind: Literal['review_outcome']
    outcome: Literal['no_change', 'no_faces', 'needs_human']


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


Operation = Annotated[Match | Remove | AddFace | CreatePerson | AddReference | Recycle | PersonNameJa | GroupNameJa
                      | AddPersonAccount | AddPersonGroup | CorrectSource | ReviewOutcome, Field(discriminator='kind')]


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1]
    batch: str = Field(pattern=r'^[0-9a-f]{32}$')
    suggestions: list[Operation] = Field(max_length=5000)


def fits(box, width, height):
    left, top, wide, high = box
    return left >= 0 and top >= 0 and wide > 0 and high > 0 and left + wide <= width and top + high <= height
