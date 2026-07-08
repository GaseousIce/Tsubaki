from anti_phishing import domain


class TestExtractUrls:
    def test_basic_urls(self):
        text = "Check this out https://example.com/page and http://test.org"
        result = domain.extract_urls(text)
        assert len(result) == 2
        assert "https://example.com/page" in result
        assert "http://test.org" in result

    def test_duplicates_removed(self):
        text = "https://example.com https://example.com"
        result = domain.extract_urls(text)
        assert len(result) == 1

    def test_case_normalized(self):
        text = "https://Example.com HTTPS://example.COM"
        result = domain.extract_urls(text)
        assert len(result) == 1
        assert result[0] == "https://example.com"

    def test_trailing_slash_stripped(self):
        text = "https://example.com/"
        result = domain.extract_urls(text)
        assert result[0] == "https://example.com"

    def test_empty_text(self):
        assert domain.extract_urls("") == []
        assert domain.extract_urls(None) == []

    def test_no_urls(self):
        assert domain.extract_urls("just some text without urls") == []

    def test_url_from_embed_url(self):
        class FakeEmbed:
            url = "https://embed.com/link"
            description = None

        result = domain.extract_urls("", embeds=[FakeEmbed()])
        assert "https://embed.com/link" in result

    def test_url_from_embed_description(self):
        class FakeEmbed:
            url = None
            description = "Visit https://desc.com/page for info"

        result = domain.extract_urls("", embeds=[FakeEmbed()])
        assert "https://desc.com/page" in result


class TestExtractHostnames:
    def test_standard_url(self):
        result = domain._extract_hostnames(["https://example.com/path?q=1"])
        assert result == {"example.com"}

    def test_url_with_port(self):
        result = domain._extract_hostnames(["https://example.com:8080/path"])
        assert result == {"example.com"}

    def test_multiple_urls(self):
        result = domain._extract_hostnames(["https://a.com", "http://b.org"])
        assert result == {"a.com", "b.org"}

    def test_invalid_url(self):
        result = domain._extract_hostnames(["not-a-url"])
        assert result == set()

    def test_empty_list(self):
        assert domain._extract_hostnames([]) == set()


class TestFindInBlacklists:
    async def test_official_blacklist_hit(self, official_domains):
        urls = ["https://phishing.xyz/evil", "https://safe.com"]
        result = await domain.find_in_blacklists(urls)
        assert result == ("phishing.xyz", "official_blacklist")

    async def test_custom_blocklist_hit(self, mock_db_with_blocklist, official_domains):
        urls = ["https://custom-blocked.com"]
        result = await domain.find_in_blacklists(urls)
        assert result[0] is not None
        assert "custom_blocklist" in result[1]

    async def test_no_match(self, official_domains):
        urls = ["https://safe-website.com"]
        result = await domain.find_in_blacklists(urls)
        assert result == (None, None)

    async def test_official_takes_priority(self, mock_db_with_blocklist, official_domains):
        urls = ["https://phishing.xyz"]
        result = await domain.find_in_blacklists(urls)
        assert result[1] == "official_blacklist"
