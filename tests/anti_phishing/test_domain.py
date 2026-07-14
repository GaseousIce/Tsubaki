from unittest.mock import AsyncMock, MagicMock, patch

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


class TestFetchBlacklist:
    async def test_fetch_blacklist_merges_both_lists(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"domains": ["phishing.xyz", "evil.com"]})

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await domain.fetch_blacklist(retries=1)

        assert "phishing.xyz" in result
        assert "evil.com" in result

    async def test_fetch_blacklist_returns_empty_on_failure(self):
        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get.side_effect = Exception("Network error")

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await domain.fetch_blacklist(retries=1)

        assert result == set()

    async def test_fetch_url_dict_response(self):
        """_fetch_url handles dict response with 'domains' key."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"domains": ["evil.com", "phishing.xyz"]})

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await domain._fetch_url("https://example.com", 1, [5], "Test")

        assert result == {"evil.com", "phishing.xyz"}

    async def test_fetch_url_retries_on_failure(self):
        """_fetch_url retries after first failure and succeeds on second attempt."""
        mock_resp = MagicMock()
        mock_resp.__aenter__.return_value = mock_resp
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=["evil.com"])

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get.side_effect = [Exception("Timeout"), mock_resp]

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("asyncio.sleep", AsyncMock()):
                result = await domain._fetch_url("https://example.com", 2, [5, 10], "Test")

        assert result == {"evil.com"}


class TestFetchOfficialBlacklist:
    async def test_success_updates_domain_official(self):
        with patch("anti_phishing.domain.fetch_blacklist", return_value={"evil.com", "phishing.xyz"}):
            from anti_phishing.__init__ import fetch_official_blacklist

            domain.official.clear()
            await fetch_official_blacklist({})
            assert "evil.com" in domain.official
            assert "phishing.xyz" in domain.official

    async def test_empty_does_not_update(self):
        with patch("anti_phishing.domain.fetch_blacklist", return_value=set()):
            from anti_phishing.__init__ import fetch_official_blacklist

            domain.official.clear()
            domain.official.add("existing.com")
            await fetch_official_blacklist({})
            assert domain.official == {"existing.com"}


class TestRealFetchBlacklist:
    """Integration tests that hit the actual GitHub API."""

    async def test_fetch_real_blacklist_returns_domains(self):
        result = await domain.fetch_blacklist(retries=1)
        assert len(result) > 0, "Real filterlist fetch returned no domains"

    async def test_fetch_real_blacklist_contains_discord_phishing(self):
        result = await domain.fetch_blacklist(retries=1)
        assert any("discord" in d for d in result), "Expected at least one 'discord' phishing domain in real filterlist"
