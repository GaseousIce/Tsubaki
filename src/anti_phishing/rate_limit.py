import time

# Keyed by user_id; value is list of (channel_id, timestamp, content) tuples.
_tracker: dict[int, list[tuple[int, float, str]]] = {}


def rate_limit_check(user_id: int, channel_id: int, content: str, rate_window: int, rate_threshold: int) -> bool:
    """
    Return True if the user has triggered the rate-limit heuristic:
    - 3+ unique channels with any link within rate_window seconds, OR
    - same content posted in 2+ channels within rate_window seconds.
    """
    now = time.time()
    entries = _tracker.get(user_id, [])

    # Prune stale entries.
    entries = [(ch, ts, ct) for ch, ts, ct in entries if now - ts <= rate_window]

    # Append current event.
    entries.append((channel_id, now, content))
    _tracker[user_id] = entries

    unique_channels = {ch for ch, _, _ in entries}
    if len(unique_channels) >= rate_threshold:
        return True

    # Same content in 2+ channels.
    content_channels = {ch for ch, _, ct in entries if ct == content}
    if len(content_channels) >= 2:
        return True

    return False


def clear_user(user_id: int) -> None:
    """Clear tracking state for a user (e.g. after they are punished)."""
    _tracker.pop(user_id, None)
