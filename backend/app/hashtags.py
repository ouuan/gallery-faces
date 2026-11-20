import re
import unicodedata
from typing import Annotated

from fastapi import HTTPException
from pydantic import AfterValidator, Field


def tag_name(value):
    return unicodedata.normalize('NFKC', value.strip()).removeprefix('#').casefold()


def normalize_hashtags(values):
    tags = set()
    for value in values:
        tag = tag_name(value)
        if not re.fullmatch(r'\w{1,100}', tag):
            raise HTTPException(400, '每个话题标签应为 1 至 100 个字母、数字或下划线，可带 # 前缀')
        tags.add(tag)
    return sorted(tags)


Hashtags = Annotated[list[str], Field(max_length=32), AfterValidator(normalize_hashtags)]


def matches_hashtags(wanted, raw, meta):
    if not wanted:
        return True
    tags = raw.get('hashtags' if meta['platform'] == 'x' else 'tags')
    if isinstance(tags, (tuple, list)):
        return any(tag_name(tag) in wanted for tag in tags if isinstance(tag, str))
    text = unicodedata.normalize('NFKC', meta['text'] or '')
    text = re.sub(r'https?://\S+', '', text, flags=re.I)
    return any(tag_name(tag) in wanted for tag in re.findall(r'#(\w+)', text))
