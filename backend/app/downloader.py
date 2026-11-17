"""gallery-dl entry point with compatibility for X's details.full_text payload."""


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


def install_policy():
    from gallery_dl.extractor.common import Extractor
    from gallery_dl.extractor.twitter import TwitterExtractor
    from gallery_dl.extractor.instagram import InstagramExtractor
    from .security import public_user, public_post

    state = {"denied": False}
    def check(callback, *args):
        try:
            return callback(*args)
        except Exception:
            state["denied"] = True
            raise ValueError("账号非公开或无法确认公开状态") from None

    initialize = Extractor.initialize
    def guarded_initialize(self):
        allowed = {"twitter": {"user", "tweets", "media", "tweet"},
                   "instagram": {"user", "posts", "photos", "reels", "post", "reel"}}
        if self.subcategory not in allowed.get(self.category, set()):
            state["denied"] = True
            raise ValueError("不支持的下载入口")
        return initialize(self)
    Extractor.initialize = guarded_initialize

    transform = TwitterExtractor._transform_tweet
    def tweet(self, raw):
        author = raw.get("author") or raw.get("core", {}).get("user_results", {}).get("result") or raw.get("user")
        check(public_user, author, "x")
        check(public_post, raw)
        check(public_post, raw.get("legacy", {}))
        return transform(self, normalize_twitter_text(raw))
    TwitterExtractor._transform_tweet = tweet
    items = TwitterExtractor.items
    def twitter_items(self):
        if self.subcategory != "tweet":
            self.login()
            check(public_user, check(self.api.user_by_screen_name, self.user), "x")
        yield from items(self)
    TwitterExtractor.items = twitter_items

    parse = InstagramExtractor._parse_post
    def post(self, raw):
        check(public_post, raw)
        owner = raw.get("user") or {}
        uid = owner.get("pk") or owner.get("id")
        if not uid:
            check(public_user, None, "instagram")
        # Bypass persistent profile caches: visibility must be checked on this attempt.
        profile = check(self.api._user_by_id_impl, str(uid))
        if str(profile.get("pk") or profile.get("id")) != str(uid):
            check(public_user, None, "instagram")
        check(public_user, profile, "instagram")
        return parse(self, raw)
    InstagramExtractor._parse_post = post
    original_items = InstagramExtractor.items
    def instagram_items(self):
        if self.subcategory in {"posts", "photos", "reels"}:
            self.login()
            check(public_user, check(self.api.user, self.item), "instagram")
        yield from original_items(self)
    InstagramExtractor.items = instagram_items
    return state


def main():
    import os
    import sys
    import gallery_dl
    from .security import download_url
    from .download_transport import install
    platform, _ = download_url(sys.argv[-1])
    network = install(platform, os.environ.get('GALLERY_FACES_POLICY_REPORT'))
    state = install_policy()
    options = ["cookies-update=false", "netrc=false",
               "retweets=false", "quoted=false", "cards=false", "twitpic=false",
               "articles=false", "videos=false", "audio=false", "previews=false"]
    for option in options:
        sys.argv[1:1] = ["-o", option]
    result = gallery_dl.main()
    return 20 if state["denied"] else 21 if network["denied"] else result


if __name__ == "__main__":
    raise SystemExit(main())
