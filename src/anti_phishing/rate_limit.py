import time
from typing import Any


class TrackerDict(dict):
    """Custom dictionary allowing tracking by (guild_id, user_id) tuple

    while preserving backwards compatibility for legacy tests querying user_id (int).
    """

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            if (0, key) in self:
                return super().__getitem__((0, key))
            for k in self:
                if isinstance(k, tuple) and len(k) == 2 and k[1] == key:
                    return super().__getitem__(k)
        return super().__getitem__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        if isinstance(key, int):
            for k in list(self.keys()):
                if isinstance(k, tuple) and len(k) == 2 and k[1] == key:
                    super().__setitem__(k, value)
                    return
            super().__setitem__((0, key), value)
        else:
            super().__setitem__(key, value)

    def __contains__(self, key: Any) -> bool:
        if isinstance(key, int):
            if (0, key) in self:
                return True
            for k in self:
                if isinstance(k, tuple) and len(k) == 2 and k[1] == key:
                    return True
            return False
        return super().__contains__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return default

    def pop(self, key: Any, *args: Any) -> Any:
        if isinstance(key, int):
            found = None
            for k in list(self.keys()):
                if (isinstance(k, tuple) and len(k) == 2 and k[1] == key) or k == key:
                    found = super().pop(k, *args)
            if found is not None:
                return found
            if args:
                return args[0]
            raise KeyError(key)
        return super().pop(key, *args)


# F07: Isolated by (guild_id, user_id), storing (channel_id, timestamp, content_hash)
_tracker: TrackerDict = TrackerDict()


def rate_limit_check(
    *args: Any,
    guild_id: int = 0,
    user_id: int | None = None,
    channel_id: int | None = None,
    content: str = "",
    rate_window: float = 10.0,
    rate_threshold: int = 3,
    **kwargs: Any,
) -> bool:
    """Check if a user is spreading links across channels within a guild.

    Supports both 6-arg (guild_id, user_id, channel_id, content, rate_window, rate_threshold)
    and 5-arg (user_id, channel_id, content, rate_window, rate_threshold).
    """
    if len(args) == 6:
        g_id, u_id, ch_id, ct, win, th = args
    elif len(args) == 5:
        g_id = guild_id
        u_id, ch_id, ct, win, th = args
    elif len(args) == 0:
        g_id = guild_id
        u_id = user_id if user_id is not None else 0
        ch_id = channel_id if channel_id is not None else 0
        ct = content
        win = rate_window
        th = rate_threshold
    else:
        raise TypeError(f"rate_limit_check takes 5 or 6 positional arguments, got {len(args)}")

    # Guard against invalid or zero limits
    if th <= 0 or win <= 0:
        return False

    now = time.time()
    key = (int(g_id), int(u_id))
    entries = _tracker.get(key, [])

    # Filter expired entries within window
    entries = [(ch, ts, c) for ch, ts, c in entries if now - ts <= win]

    # F07: Store integer hash of content rather than raw string body to prevent memory leaks
    content_hash = hash(ct)
    entries.append((int(ch_id), now, content_hash))

    max_entries = th * 2
    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    _tracker[key] = entries

    # Check distinct channels in window
    unique_channels = {ch for ch, _, _ in entries}
    if len(unique_channels) >= th:
        return True

    # Check identical content posted across 2+ channels
    content_channels = {ch for ch, _, c in entries if c == content_hash or c == ct}
    if len(content_channels) >= 2:
        return True

    return False


def clear_user(*args: Any, user_id: int | None = None, guild_id: int | None = None) -> None:
    """Clear rate-limit tracking for a user.

    Supports clear_user(user_id), clear_user(guild_id, user_id),
    or keyword arguments.
    """
    if len(args) == 2:
        g_id, u_id = args
    elif len(args) == 1:
        g_id = guild_id
        u_id = args[0]
    elif len(args) == 0:
        g_id = guild_id
        u_id = user_id
    else:
        raise TypeError(f"clear_user takes 1 or 2 positional arguments, got {len(args)}")

    if u_id is None:
        return

    if g_id is not None and g_id != 0:
        _tracker.pop((int(g_id), int(u_id)), None)
    else:
        _tracker.pop(int(u_id), None)


def prune_stale_entries(window_seconds: int = 3600) -> None:
    """Purge stale rate-limit entries for inactive users/guilds."""
    now = time.time()
    stale_keys = []
    for key, entries in list(_tracker.items()):
        active_entries = [entry for entry in entries if now - entry[1] <= window_seconds]
        if not active_entries:
            stale_keys.append(key)
        else:
            _tracker[key] = active_entries

    for key in stale_keys:
        _tracker.pop(key, None)
