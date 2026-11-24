from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict


class XScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    retweets: bool = False
    quoted: bool = False


class InstagramScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stories: bool = True
    tagged: bool = True


class ImportScope(XScope, InstagramScope):
    reposts: bool = False


def effective_scope(url, options):
    parsed = urlsplit(url)
    path = parsed.path.strip('/')
    if '/' in path and not path.startswith('i/lists/'):
        return {}
    if parsed.hostname.removeprefix('www.') in ('twitter.com', 'x.com'):
        return {key: options[key] for key in XScope.model_fields}
    return {key: options[key] for key in ('stories', 'tagged', 'reposts')}


def feeds(payload):
    scope = payload.get('scope')
    if not scope or urlsplit(payload['url']).path.strip('/').startswith('i/lists/'):
        return [None]
    if 'retweets' in scope:
        return ['media', *(['tweets'] if scope['quoted'] else ()), *(['reposts'] if scope['retweets'] else ())]
    return [*(['stories'] if scope['stories'] else ()), 'posts', *(['tagged'] if scope['tagged'] else ()),
            *(['reposts'] if scope.get('reposts') else ())]
