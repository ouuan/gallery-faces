"""gallery-dl entry point with compatibility for X's details.full_text payload."""


def date_options(start=None, end=None):
    """Translate inclusive UTC lower / exclusive upper bounds to gallery-dl."""
    from datetime import datetime, timedelta, timezone

    options = []
    if start:
        lower = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
        # gallery-dl compares second-resolution dates strictly after this value.
        options += ["--date-after", (lower - timedelta(seconds=1)).isoformat()]
    if end:
        options += ["--date-before", end]
    if start or end:
        predicate = "locals().get('date')"
        if start:
            bound = f"datetime({lower.year}, {lower.month}, {lower.day}, {lower.hour}, {lower.minute}, {lower.second})"
            # Run before the native date predicate: an old pinned post must not
            # stop extraction of the chronological feed that follows it.
            predicate += f" and (not locals().get('pinned') or date >= {bound})"
        options += ["--post-filter", predicate]
    return options


def normalize_twitter_text(tweet):
    details = tweet.get("details")
    if not isinstance(details, dict):
        return tweet
    text = details.get("full_text")
    legacy = tweet.get("legacy", tweet)
    if not isinstance(text, str) or not text.strip() or legacy.get("full_text") or legacy.get("text"):
        return tweet
    result = dict(tweet)
    target = dict(legacy) if "legacy" in tweet else result
    target["full_text"] = text
    entities = dict(target.get("entities") or {})
    for key, values in (
        ("urls", tweet.get("url_entities")),
        ("hashtags", details.get("hashtag_entities")),
        ("user_mentions", tweet.get("mention_entities")),
    ):
        if key not in entities and isinstance(values, list):
            entities[key] = values
    target["entities"] = entities
    if "legacy" in tweet:
        result["legacy"] = target
    return result


def install_policy(report_path=None, feed=None, scope=None):
    from gallery_dl.extractor.common import Extractor
    from gallery_dl.extractor.twitter import TwitterExtractor
    from gallery_dl.extractor.instagram import InstagramExtractor, InstagramStoriesExtractor
    from .security import public_user, public_post

    state = {"denied": False}
    def deny(message):
        state['denied'] = True
        if report_path:
            from pathlib import Path
            Path(report_path).write_text(message, encoding='utf-8')
        raise ValueError(message) from None

    def check(callback, *args):
        try:
            return callback(*args)
        except Exception:
            deny('账号非公开或无法确认公开状态')

    initialize = Extractor.initialize
    def guarded_initialize(self):
        allowed = {"twitter": {"user", "tweets", "media", "tweet", "list"},
                   "instagram": {"user", "posts", "photos", "reels", "post", "reel"}}
        if feed in {'stories', 'tagged', 'reposts'}:
            allowed['instagram'].add(feed)
        if feed == 'reposts':
            allowed['twitter'].add(feed)
        if self.subcategory not in allowed.get(self.category, set()):
            deny('不支持的下载入口')
        return initialize(self)
    Extractor.initialize = guarded_initialize

    transform = TwitterExtractor._transform_tweet
    def public_tweet(raw):
        author = raw.get("author") or raw.get("core", {}).get("user_results", {}).get("result") or raw.get("user")
        check(public_user, author, "x")
        check(public_post, raw)
        check(public_post, raw.get("legacy", {}))

    def tweet(self, raw):
        public_tweet(raw)
        legacy = raw.get('legacy', raw)
        via_retweet = bool(legacy.get('retweeted_status_id_str') or raw.get('via_retweet'))
        shared_id = legacy.get('quoted_by_id_str')
        if scope and legacy.get('retweeted_status_id_str'):
            if core := raw.get('core'):
                check(public_user, core.get('user_results', {}).get('result'), 'x')
            original = (legacy.get('retweeted_status_result') or {}).get('result') or {}
            shared_id = legacy['id_str']
            raw = original.get('tweet', original)
            public_tweet(raw)
        data = transform(self, normalize_twitter_text(raw))
        if via_retweet:
            data['via_retweet'] = True
        if legacy.get('quoted_by_id_str'):
            data['via_quote'] = True
        if scope and shared_id:
            data['source_date'] = data['date']
            data['date'] = self._tweetid_to_datetime(int(shared_id))
        return data
    TwitterExtractor._transform_tweet = tweet
    items = TwitterExtractor.items
    def twitter_items(self):
        if self.subcategory not in {"tweet", "list"}:
            self.login()
            check(public_user, check(self.api.user_by_screen_name, self.user), "x")
        if scope and scope.get('quoted'):
            original_tweets = self.tweets
            def checked_quotes():
                parent = None
                for raw in original_tweets():
                    legacy = raw.get('legacy', raw)
                    if parent_id := legacy.get('quoted_by_id_str'):
                        if not parent or parent.get('legacy', parent).get('id_str') != parent_id:
                            continue
                        if not scope.get('retweets') and 'retweeted_status_id_str' in parent.get('legacy', parent):
                            continue
                        public_tweet(parent)
                        if parent.get('legacy', parent).get('retweeted_status_id_str'):
                            raw['via_retweet'] = True
                        if parent.get('pinned'):
                            raw['pinned'] = True
                    else:
                        parent = raw
                    yield raw
            self.tweets = checked_quotes
        yield from items(self)
    TwitterExtractor.items = twitter_items

    parse = InstagramExtractor._parse_post
    def public_owner(self, owner):
        uid = owner.get("pk") or owner.get("id")
        if not uid:
            check(public_user, None, "instagram")
        # Bypass persistent profile caches: visibility must be checked on this attempt.
        profile = check(self.api._user_by_id_impl, str(uid))
        if str(profile.get("pk") or profile.get("id")) != str(uid):
            check(public_user, None, "instagram")
        check(public_user, profile, "instagram")

    def post(self, raw):
        check(public_post, raw)
        public_owner(self, raw.get('user') or {})
        data = parse(self, raw)
        if feed == 'stories':
            item = raw['items'][0]
            data.update(post_id=item['pk'], post_shortcode=item.get('code'),
                        post_url=f"{self.root}/stories/{self.user}/{item['pk']}/")
        return data
    InstagramExtractor._parse_post = post
    story_reels = InstagramStoriesExtractor.posts
    def stories(self):
        for reel in story_reels(self):
            for item in sorted(reel['items'], key=lambda item: item['taken_at'], reverse=True):
                check(public_post, item)
                for field in ('user', 'owner', 'reshared_story_media_author'):
                    if owner := item.get(field):
                        public_owner(self, owner)
                yield {**reel, 'seen': item['taken_at'], 'taken_at': item['taken_at'], 'items': [item]}
    if feed == 'stories':
        InstagramStoriesExtractor.posts = stories
    original_items = InstagramExtractor.items
    def instagram_items(self):
        if self.subcategory in {"posts", "photos", "reels", "tagged", "stories", "reposts"}:
            self.login()
            owner = check(self.api.user, self.user if self.subcategory == 'stories' else self.item)
            check(public_user, owner, 'instagram')
            if feed in {'tagged', 'stories', 'reposts'}:
                public_owner(self, owner)
        yield from original_items(self)
    InstagramExtractor.items = instagram_items
    return state


def install_library_filter(report_path=None, restore_id=None, hashtags=(), cache_post=None, active=None, directory=None, denied=None):
    """Runs after gallery-dl's date/media filters, before any media request."""
    import json
    from gallery_dl.job import DownloadJob
    from .db import connect
    from .hashtags import matches_hashtags
    from .metadata import metadata, publisher_blocked, source_image

    original = DownloadJob.handle_url
    wanted = frozenset(hashtags)
    if cache_post:
        from .security import download_url
        from urllib.parse import urlsplit
        platform, canonical = download_url(cache_post)
        parts = urlsplit(canonical).path.strip('/').split('/')
        if platform == 'x' and len(parts) >= 3 and parts[1] == 'status':
            post_key = parts[2]
        elif platform == 'instagram' and len(parts) == 2 and parts[0] in ('p', 'reel', 'tv'):
            post_key = parts[1]
        else:
            raise ValueError('Cache recovery requires a single post')

    def handle_url(self, url, raw):
        meta = metadata({**raw, 'category': self.extractor.category,
                         'subcategory': getattr(self.extractor, 'subcategory', raw.get('subcategory'))}, '')
        if not matches_hashtags(wanted, raw, meta):
            return
        if active:
            from .metadata import in_date_range
            if denied():
                raise ValueError('下载被安全策略拒绝')
            if not in_date_range(meta, active.payload.get('start'), active.payload.get('end')):
                return
            if raw.get('source_date') is not None:
                meta['date'] = metadata({**raw, 'category': self.extractor.category, 'date': raw['source_date']}, '')['date']
            if active.skip(meta):
                return
            def completed(pathfmt):
                if denied():
                    raise ValueError('下载被安全策略拒绝')
                active.stage(pathfmt.path, meta, directory)
                active.import_ready()
            if not self.hooks:
                self.hooks = {}
            callbacks = self.hooks.setdefault('after', [])
            callbacks.append(completed)
            try:
                original(self, url, raw)
                if self.status:
                    raise ValueError('媒体下载失败')
            finally:
                callbacks.remove(completed)
            return
        if cache_post:
            keys = (meta['key'], raw.get('post_shortcode'), raw.get('shortcode'))
            if meta['platform'] == platform and post_key in keys:
                return original(self, url, raw)
            return
        with connect() as db:
            if restore_id is None and publisher_blocked(db, meta):
                return
            known = source_image(db, meta)
        if restore_id is not None:
            if not known or known["id"] != restore_id:
                return
        elif known:
            if report_path:
                # Store only normalized source fields, never signed media URLs,
                # downloader objects, cookies, or transport headers.
                with open(report_path, "a", encoding="utf-8") as report:
                    report.write(json.dumps({"image_id": known["id"], "meta": meta}) + "\n")
            return
        return original(self, url, raw)

    DownloadJob.handle_url = handle_url


def install_cursors(active, denied):
    from gallery_dl.extractor.instagram import InstagramAPI, InstagramExtractor
    from gallery_dl.extractor.twitter import TwitterAPI, TwitterExtractor, TwitterMediaExtractor

    TwitterMediaExtractor.tweets = lambda extractor: extractor.api.user_media_photos(extractor.user)

    def isolate_detail(method):
        def nested(api, *args, **kwargs):
            extractor = api.extractor
            previous = getattr(extractor, '_reading_media_detail', False)
            extractor._reading_media_detail = True
            try:
                yield from method(api, *args, **kwargs)
            finally:
                extractor._reading_media_detail = previous
        return nested
    InstagramAPI.media = isolate_detail(InstagramAPI.media)
    TwitterAPI.tweet_detail = isolate_detail(TwitterAPI.tweet_detail)

    feeds = {'tweets', 'media', 'list', 'posts', 'photos', 'reels', 'tagged', 'reposts'}
    def wrap(cls):
        initial, update = cls._init_cursor, cls._update_cursor
        def start(extractor):
            if getattr(extractor, '_reading_media_detail', False):
                return None
            if extractor.subcategory in feeds and active.cursor:
                active.started_from_cursor = True
                return active.cursor
            return initial(extractor)
        def advance(extractor, cursor):
            if getattr(extractor, '_reading_media_detail', False):
                return cursor
            if cursor and extractor.subcategory in feeds and not denied():
                active.checkpoint(cursor)
            return update(extractor, cursor)
        cls._init_cursor, cls._update_cursor = start, advance
    wrap(InstagramExtractor)
    wrap(TwitterExtractor)


def bind_parent(expected_pid):
    import ctypes
    import os
    import signal
    import sys
    if sys.platform.startswith('linux'):
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'prctl')
    if os.getppid() != expected_pid:
        raise SystemExit(1)


def main():
    import json
    import os
    import sys
    if parent := os.environ.get('GALLERY_FACES_PARENT'):
        bind_parent(int(parent))
    import gallery_dl
    from .security import download_url
    from .download_transport import install
    platform, _ = download_url(sys.argv[-1])
    network = install(platform, os.environ.get('GALLERY_FACES_POLICY_REPORT'))
    active = directory = None
    scope = {}
    feed = None
    def denied():
        return state['denied'] or network['denied']
    if claim := os.environ.get('GALLERY_FACES_ROUND'):
        from pathlib import Path
        from .download_round import DownloadRound
        active = DownloadRound(*map(int, claim.split(':')))
        scope = active.payload.get('scope') or {}
        feed = active.feeds[active.feed_index]
        active.resume()
        from .download_part import install as install_parts
        install_parts(active)
        directory = Path(os.environ['GALLERY_FACES_MEDIA_DIR'])
        install_cursors(active, denied)
    state = install_policy(os.environ.get('GALLERY_FACES_POLICY_REPORT'), feed, scope)
    restore_id = os.environ.get("GALLERY_FACES_RESTORE_IMAGE")
    install_library_filter(os.environ.get("GALLERY_FACES_SKIPPED_REPORT"), int(restore_id) if restore_id else None,
                           json.loads(os.environ.get("GALLERY_FACES_HASHTAGS", "[]")), os.environ.get('GALLERY_FACES_CACHE_POST'),
                           active, directory, denied)
    options = ["cookies-update=false", "netrc=false",
               'retweets=' + ('true' if scope.get('retweets') else 'false'),
               'quoted=' + ('true' if scope.get('quoted') else 'false'), "cards=false", "twitpic=false",
               "articles=false", "videos=false", "audio=false", "previews=false"]
    if feed:
        options.append('include=' + feed)
    if scope.get('retweets') or scope.get('quoted'):
        options.append('unique=false')
    for option in options:
        sys.argv[1:1] = ["-o", option]
    result = gallery_dl.main()
    if not result and active and not denied() and active.next_feed():
        return 75
    if result and active and active.started_from_cursor and not active.advanced and not active.saw_item and not denied():
        active.checkpoint(None)
        return 75
    return 20 if state["denied"] else 21 if network["denied"] else result


if __name__ == "__main__":
    raise SystemExit(main())
