"""Unit tests for the curated feed catalog (pure data + functions).

Mirrors the style of ``tests/test_rsshub.py``: pure-function tests, no network,
no mocks. Covers topic matching (CN/EN, multi-topic, dedup, misses), defensive
input handling, and catalog data integrity.
"""

from app.services.feed_catalog import CATALOG, catalog_candidate_urls, list_topics


class TestCatalogCandidateUrls:
    def test_chinese_intent_matches(self):
        """中文意图命中主题。"""
        urls = catalog_candidate_urls({"intent": "我想看 AI 和大模型动态"})
        # ai_ml 主题被命中,返回其 feeds
        ai_feeds = CATALOG["ai_ml"]["feeds"]
        assert len(urls) == len(ai_feeds)
        for f in ai_feeds:
            assert f in urls

    def test_english_search_terms_match(self):
        """英文 search_terms 命中主题。"""
        urls = catalog_candidate_urls({"search_terms": ["machine learning", "llm"]})
        assert len(urls) > 0
        ai_feeds = CATALOG["ai_ml"]["feeds"]
        assert all(f in urls for f in ai_feeds)

    def test_case_insensitive(self):
        """匹配大小写不敏感。"""
        lower = catalog_candidate_urls({"intent": "frontend"})
        upper = catalog_candidate_urls({"intent": "FRONTEND"})
        assert lower == upper
        assert len(lower) > 0

    def test_multiple_topics_match_and_merge(self):
        """一段意图同时命中多个主题时,合并各主题 feeds。"""
        # "css 和 swift" 同时命中 frontend(css)和 mobile(swift),且不波及其他主题
        urls = catalog_candidate_urls({"intent": "css 和 swift 移动 app"})
        fe_feeds = set(CATALOG["frontend"]["feeds"])
        mobile_feeds = set(CATALOG["mobile"]["feeds"])
        merged = fe_feeds | mobile_feeds
        assert set(urls) == merged

    def test_dedup_across_topics(self):
        """多个主题共享同一 feed(如 HN)时,结果里只出现一次。"""
        # HN frontpage 同时在 ai_ml / programming / frontend / open_source / mobile
        urls = catalog_candidate_urls({"intent": "AI 编程 前端 开源 移动"})
        # 列表中不应有重复 URL
        assert len(urls) == len(set(urls)), "duplicate URLs in result"
        # HN frontpage 应该只出现一次
        assert urls.count("https://hnrss.org/frontpage") == 1

    def test_name_field_matches(self):
        """plan['name'] 也参与匹配。"""
        urls = catalog_candidate_urls({"name": "网络安全速报"})
        sec_feeds = CATALOG["security"]["feeds"]
        assert len(urls) == len(sec_feeds)
        assert all(f in urls for f in sec_feeds)

    def test_all_text_fields_combined(self):
        """intent + name + search_terms 拼接后一起参与匹配。"""
        # 单独任一字段都不够长,但合起来命中
        urls = catalog_candidate_urls(
            {
                "name": "极客",
                "search_terms": ["open source"],
            }
        )
        assert len(urls) > 0
        assert "https://github.blog/feed/" in urls

    def test_no_match_returns_empty(self):
        """无关主题不命中,返回空列表。"""
        assert catalog_candidate_urls({"intent": "美食烹饪和烘焙"}) == []
        assert catalog_candidate_urls({"intent": "旅游攻略"}) == []

    def test_empty_plan(self):
        """空 plan dict 不崩溃,返回空。"""
        assert catalog_candidate_urls({}) == []

    def test_none_values_tolerated(self):
        """字段值为 None 时不崩溃。"""
        assert catalog_candidate_urls({"intent": None, "name": None, "search_terms": None}) == []

    def test_non_dict_input_returns_empty(self):
        """非 dict 输入(如 None / list)安全降级。"""
        assert catalog_candidate_urls(None) == []  # type: ignore[arg-type]
        assert catalog_candidate_urls("not a dict") == []  # type: ignore[arg-type]
        assert catalog_candidate_urls([]) == []  # type: ignore[arg-type]

    def test_partial_plan_tolerated(self):
        """只有部分字段的 plan 不崩溃。"""
        # 只有 search_terms,无 intent/name
        urls = catalog_candidate_urls({"search_terms": ["security"]})
        assert len(urls) > 0

    def test_empty_strings_ignored(self):
        """空字符串/纯空白字段被忽略。"""
        assert catalog_candidate_urls({"intent": "", "name": "   "}) == []
        assert catalog_candidate_urls({"search_terms": ["", "  "]}) == []

    def test_preserves_topic_feed_order(self):
        """返回顺序稳定:按 CATALOG 字典顺序遍历主题,主题内按 feeds 列表顺序。"""
        urls = catalog_candidate_urls({"intent": "AI"})
        ai_feeds = CATALOG["ai_ml"]["feeds"]
        # ai_ml 是第一个命中的主题,其 feeds 应该排在最前
        assert urls[: len(ai_feeds)] == ai_feeds


class TestCatalogDataIntegrity:
    """Catalog 数据完整性 —— 防止手误导致的坏数据。"""

    def test_every_feed_url_is_http(self):
        """所有 feed URL 必须是 http/https 开头。"""
        for topic_key, topic in CATALOG.items():
            for url in topic["feeds"]:
                assert url.startswith(("http://", "https://")), f"topic '{topic_key}' has non-http feed: {url}"

    def test_every_feed_url_is_unique_globally(self):
        """同一 URL 不应在不同位置出现重复(虽然跨主题共享是允许的,
        但同一主题内部不应有重复)。"""
        for topic_key, topic in CATALOG.items():
            feeds = topic["feeds"]
            assert len(feeds) == len(set(feeds)), f"topic '{topic_key}' has duplicate feed URLs"

    def test_every_topic_has_keywords_and_feeds(self):
        """每个主题必须有 label + 非空 keywords + 非空 feeds。"""
        for topic_key, topic in CATALOG.items():
            assert topic.get("label"), f"topic '{topic_key}' missing label"
            assert (
                isinstance(topic.get("keywords"), list) and topic["keywords"]
            ), f"topic '{topic_key}' missing keywords"
            assert isinstance(topic.get("feeds"), list) and topic["feeds"], f"topic '{topic_key}' missing feeds"

    def test_no_empty_keywords(self):
        """keywords 中不应有空字符串或纯空白。"""
        for topic_key, topic in CATALOG.items():
            for kw in topic["keywords"]:
                assert kw and kw.strip(), f"topic '{topic_key}' has empty keyword"

    def test_keyword_normalisation(self):
        """文档约定 keywords 为小写匹配词。允许中文(大小写不敏感由
        匹配函数保证),但英文 keyword 应为小写以保持一致性。"""
        for topic_key, topic in CATALOG.items():
            for kw in topic["keywords"]:
                # 英文 keyword 应小写;含中文的跳过
                if kw.isascii():
                    assert kw == kw.lower(), f"topic '{topic_key}' english keyword not lowercase: {kw!r}"


class TestListTopics:
    def test_returns_all_topics(self):
        topics = list_topics()
        assert len(topics) == len(CATALOG)

    def test_entry_shape(self):
        topics = list_topics()
        for t in topics:
            assert set(t.keys()) == {"key", "label", "keywords", "feed_count"}
            assert isinstance(t["keywords"], list)
            assert isinstance(t["feed_count"], int)
            assert t["feed_count"] > 0

    def test_keys_match_catalog(self):
        topics = list_topics()
        assert {t["key"] for t in topics} == set(CATALOG.keys())
