from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

    def test_extract_urls_with_query_ports_and_anchors(self):
        text = "Visit https://evil.com:8443/login?token=secret#dashboard today"
        result = domain.extract_urls(text)
        assert len(result) == 1
        assert result[0] == "https://evil.com:8443/login?token=secret#dashboard"

    def test_extract_urls_strips_trailing_sentence_punctuation(self):
        text = "Check out https://evil.com/page. And http://test.org/claim!"
        result = domain.extract_urls(text)
        assert result == ["https://evil.com/page", "http://test.org/claim"]

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

    def test_url_from_attachment_description(self):
        class FakeAttachment:
            description = "Scan QR code or click https://qr-phish.xyz/claim"

        result = domain.extract_urls("", attachments=[FakeAttachment()])
        assert "https://qr-phish.xyz/claim" in result

    def test_url_from_embed_title_and_fields(self):
        class FakeField:
            name = "Link"
            value = "Claim at https://field-url.com"

        class FakeEmbed:
            title = "Free gift https://title-url.com"
            fields = [FakeField()]
            url = None
            description = None

        result = domain.extract_urls("", embeds=[FakeEmbed()])
        assert "https://title-url.com" in result
        assert "https://field-url.com" in result

    def test_url_from_embed_footer_and_author(self):
        class FakeFooter:
            text = "Help at https://footer-link.com"

        class FakeAuthor:
            url = "https://author-link.com"

        class FakeEmbed:
            url = None
            description = None
            title = None
            fields = []
            footer = FakeFooter()
            author = FakeAuthor()

        result = domain.extract_urls("", embeds=[FakeEmbed()])
        assert "https://footer-link.com" in result
        assert "https://author-link.com" in result


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

    async def test_subdomain_matches_official_blacklist(self, official_domains):
        urls = ["https://claim.free.phishing.xyz/nitro"]
        result = await domain.find_in_blacklists(urls)
        assert result == ("claim.free.phishing.xyz", "official_blacklist")

    async def test_subdomain_matches_custom_blocklist(self, mock_db_with_blocklist, official_domains):
        urls = ["https://auth.custom-blocked.com/login"]
        result = await domain.find_in_blacklists(urls)
        assert result[0] == "auth.custom-blocked.com"
        assert "custom_blocklist" in result[1]

    async def test_no_match(self, official_domains):
        urls = ["https://safe-website.com"]
        result = await domain.find_in_blacklists(urls)
        assert result == (None, None)

    async def test_official_takes_priority(self, mock_db_with_blocklist, official_domains):
        urls = ["https://phishing.xyz"]
        result = await domain.find_in_blacklists(urls)
        assert result[1] == "official_blacklist"

    async def test_custom_blocklist_db_exception_continues(self, official_domains):
        urls = ["https://safe-site.com"]
        with patch("anti_phishing.domain.db.get_blocklist_source", side_effect=Exception("DB fail")):
            result = await domain.find_in_blacklists(urls)
            assert result == (None, None)


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


class TestTrailingDotNormalization:
    def test_extract_hostnames_trailing_dot(self):
        result = domain._extract_hostnames(["https://evil.com./claim"])
        assert "evil.com" in result

    def test_domain_candidates_trailing_dot(self):
        candidates = domain._domain_candidates("evil.com.")
        assert candidates == ["evil.com"]

    async def test_find_in_blacklists_trailing_dot_matches_official(self, official_domains):
        urls = ["https://phishing.xyz./claim"]
        result = await domain.find_in_blacklists(urls)
        assert result == ("phishing.xyz", "official_blacklist")


class TestHomoglyphAndIDNNormalization:
    def test_extract_hostnames_cyrillic_homoglyph(self):
        # Using Cyrillic 'і' (\u0456)
        urls = ["https://d\u0456scord.com/login"]
        result = domain._extract_hostnames(urls)
        assert "d\u0456scord.com" in result
        assert "xn--dscord-pvf.com" in result

    def test_extract_hostnames_punycode_input(self):
        urls = ["https://xn--dscord-pvf.com/login"]
        result = domain._extract_hostnames(urls)
        assert "xn--dscord-pvf.com" in result
        assert "d\u0456scord.com" in result

    async def test_find_in_blacklists_homoglyph_matches_punycode_official(self):
        domain.official.add("xn--dscord-pvf.com")
        urls = ["https://d\u0456scord.com/login"]
        result = await domain.find_in_blacklists(urls)
        assert result[1] == "official_blacklist"


class TestTyposquattingEngine:
    async def test_check_typosquats_catches_discord_mimic(self):
        urls = ["https://dlscord.com/login"]
        result = await domain.check_typosquats(urls, check_db=False)
        assert result == ("dlscord.com", "typosquat (discord.com)")

    async def test_check_typosquats_catches_nitro_gift_combo(self):
        urls = ["https://discord-nitro.gift/claim"]
        result = await domain.check_typosquats(urls, check_db=False)
        assert result == ("discord-nitro.gift", "typosquat (discord.com)")

    async def test_check_typosquats_catches_steam_mimic(self):
        urls = ["https://steamcommunitv.com/trade"]
        result = await domain.check_typosquats(urls, check_db=False)
        assert result == ("steamcommunitv.com", "typosquat (steamcommunity.com)")

    async def test_check_typosquats_legitimate_discord_not_flagged(self):
        urls = [
            "https://discord.com",
            "https://canary.discord.com",
            "https://discord.gg/invite",
            "https://discordapp.com/channels",
            "https://discord.gift/nitrocode",
        ]
        result = await domain.check_typosquats(urls, check_db=False)
        assert result == (None, None)

    async def test_check_typosquats_legitimate_steam_not_flagged(self):
        urls = ["https://steamcommunity.com", "https://store.steampowered.com"]
        result = await domain.check_typosquats(urls, check_db=False)
        assert result == (None, None)

    async def test_check_typosquats_homoglyph_folding(self):
        # 'dіscord-nitro.ru' with Cyrillic 'і'
        urls = ["https://d\u0456scord-nitro.ru"]
        result = await domain.check_typosquats(urls, check_db=False)
        assert result[0] is not None
        assert "typosquat (discord.com)" in result[1]

    async def test_check_typosquats_custom_db_pattern(self):
        urls = ["https://custom-phish.net/login"]
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(rows=[("custom-phish", "discord.com")]))
        with patch("anti_phishing.domain.db.get_db", AsyncMock(return_value=mock_db)):
            result = await domain.check_typosquats(urls, check_db=True)
            assert result == ("custom-phish.net", "typosquat (discord.com)")

    async def test_populate_default_typosquats(self):
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        with patch("anti_phishing.domain.db.get_db", AsyncMock(return_value=mock_db)):
            inserted = await domain.populate_default_typosquats()
            assert inserted == len(domain.DEFAULT_TYPOSQUAT_PATTERNS)
            assert mock_db.execute.call_count == len(domain.DEFAULT_TYPOSQUAT_PATTERNS)


class TestEmbedUrlCompleteness:
    def test_url_from_embed_author_name(self):
        class FakeAuthor:
            name = "Security Check https://auth-verify.xyz/login"
            url = None

        class FakeEmbed:
            url = None
            description = None
            title = None
            fields = []
            footer = None
            author = FakeAuthor()

        result = domain.extract_urls("", embeds=[FakeEmbed()])
        assert "https://auth-verify.xyz/login" in result

    def test_url_from_embed_image_and_thumbnail(self):
        class FakeMedia:
            url = "https://cdn-evil.com/image.png"

        class FakeThumb:
            url = "https://cdn-evil.com/thumb.png"

        class FakeEmbed:
            url = None
            description = None
            title = None
            fields = []
            footer = None
            author = None
            image = FakeMedia()
            thumbnail = FakeThumb()

        result = domain.extract_urls("", embeds=[FakeEmbed()])
        assert "https://cdn-evil.com/image.png" in result
        assert "https://cdn-evil.com/thumb.png" in result


class TestParenthesesAndSchemeHandling:
    def test_url_query_parentheses_preserved(self):
        text = "Visit https://evil.com/page?ref=(secret_token)&id=1 today"
        result = domain.extract_urls(text)
        assert result == ["https://evil.com/page?ref=(secret_token)&id=1"]

    def test_url_markdown_unbalanced_parentheses_stripped(self):
        text = "Check [this link](https://evil.com/claim) now!"
        result = domain.extract_urls(text)
        assert result == ["https://evil.com/claim"]

    def test_url_balanced_parentheses_wikipedia(self):
        text = "Read https://en.wikipedia.org/wiki/Phishing_(disambiguation) for details"
        result = domain.extract_urls(text)
        assert result == ["https://en.wikipedia.org/wiki/phishing_(disambiguation)"]

    def test_extract_urls_uppercase_scheme(self):
        text = "Check HTTPS://EVIL.COM/PATH and HTTP://TEST.ORG"
        result = domain.extract_urls(text)
        assert "https://evil.com/path" in result
        assert "http://test.org" in result


class TestAllowedDomainSet:
    async def test_find_in_blacklists_bypasses_allowed_domain(self, official_domains):
        domain.allowed.add("phishing.xyz")
        try:
            urls = ["https://phishing.xyz/claim"]
            result = await domain.find_in_blacklists(urls)
            assert result == (None, None)
        finally:
            domain.allowed.clear()

    async def test_check_typosquats_bypasses_allowed_domain(self):
        domain.allowed.add("dlscord.com")
        try:
            urls = ["https://dlscord.com/login"]
            result = await domain.check_typosquats(urls, check_db=False)
            assert result == (None, None)
        finally:
            domain.allowed.clear()


class TestPublicSuffixIsolation:
    def test_domain_candidates_public_suffixes(self):
        assert domain._domain_candidates("innocent.github.io") == ["innocent.github.io"]
        assert domain._domain_candidates("sub.site.co.uk") == ["sub.site.co.uk", "site.co.uk"]
        assert domain._domain_candidates("sub.evil.com") == ["sub.evil.com", "evil.com"]
        assert domain._domain_candidates("evil.com") == ["evil.com"]
        assert domain._domain_candidates("app.vercel.app") == ["app.vercel.app"]
        assert domain._domain_candidates("pages.dev") == ["pages.dev"]

    async def test_find_in_blacklists_public_suffix_isolation(self):
        domain.allowed.add("innocent.github.io")
        domain.official.add("evil.github.io")
        try:
            assert await domain.find_in_blacklists(["https://innocent.github.io"], check_custom_blocklist=False) == (
                None,
                None,
            )
            assert await domain.find_in_blacklists(["https://evil.github.io"], check_custom_blocklist=False) == (
                "evil.github.io",
                "official_blacklist",
            )
        finally:
            domain.allowed.clear()
            domain.official.discard("evil.github.io")


class TestClientSessionReuse:
    async def test_fetch_blacklist_reuses_provided_session(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"domains": ["phishing.xyz"]})

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        result = await domain.fetch_blacklist(retries=1, session=mock_session)
        assert "phishing.xyz" in result
        # Both calls ran through the provided session
        assert mock_session.get.call_count == 2


@pytest.mark.network
class TestRealFetchBlacklist:
    """Integration tests that hit the actual GitHub API."""

    async def test_fetch_real_blacklist_returns_domains(self):
        result = await domain.fetch_blacklist(retries=1)
        assert len(result) > 0, "Real filterlist fetch returned no domains"

    async def test_fetch_real_blacklist_contains_discord_phishing(self):
        result = await domain.fetch_blacklist(retries=1)
        assert any("discord" in d for d in result), "Expected at least one 'discord' phishing domain in real filterlist"
