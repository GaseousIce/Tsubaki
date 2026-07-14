import time

_tracker: dict[int, list[tuple[int, float, str]]] = {}


def rate_limit_check(user_id: int, channel_id: int, content: str, rate_window: int, rate_threshold: int) -> bool:
    now = time.time()
    entries = _tracker.get(user_id, [])

    entries = [(ch, ts, ct) for ch, ts, ct in entries if now - ts <= rate_window]

    entries.append((channel_id, now, content))

    max_entries = rate_threshold * 2
    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    _tracker[user_id] = entries

    unique_channels = {ch for ch, _, _ in entries}
    if len(unique_channels) >= rate_threshold:
        return True

    content_channels = {ch for ch, _, ct in entries if ct == content}
    if len(content_channels) >= 2:
        return True

    return False


def clear_user(user_id: int) -> None:
    _tracker.pop(user_id, None)


def prune_stale_entries(window_seconds: int = 3600) -> None:
    """Purge stale rate-limit entries for users who have been inactive."""
    now = time.time()
    stale_keys = []
    for user_id, entries in list(_tracker.items()):
        active_entries = [entry for entry in entries if now - entry[1] <= window_seconds]
        if not active_entries:
            stale_keys.append(user_id)
        else:
            _tracker[user_id] = active_entries

    for key in stale_keys:
        _tracker.pop(key, None)
