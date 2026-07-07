import hashlib
import time

# Keyed by user_id; value is list of (channel_id, timestamp, content) tuples.
_tracker: dict[int, list[tuple[int, float, str]]] = {}
_last_global_prune: float = 0.0
GLOBAL_PRUNE_INTERVAL = 3600  # 1 hour


def rate_limit_check(user_id: int, channel_id: int, content: str, rate_window: int, rate_threshold: int) -> bool:
    """
    Return True if the user has triggered the rate-limit heuristic:
    - 3+ unique channels with any link within rate_window seconds, OR
    - same content posted in 2+ channels within rate_window seconds.
    """
    global _last_global_prune
    now = time.time()

    # Periodic global prune to prevent memory leaks from inactive users.
    if now - _last_global_prune > GLOBAL_PRUNE_INTERVAL:
        expired_keys = []
        for uid, entries in list(_tracker.items()):
            valid_entries = [(ch, ts, ct) for ch, ts, ct in entries if now - ts <= rate_window]
            if not valid_entries:
                expired_keys.append(uid)
            else:
                _tracker[uid] = valid_entries
        for uid in expired_keys:
            _tracker.pop(uid, None)
        _last_global_prune = now

    entries = _tracker.get(user_id, [])

    # Prune stale entries.
    entries = [(ch, ts, ct) for ch, ts, ct in entries if now - ts <= rate_window]

    # Hash the content to save memory
    content_hash = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()

    # Append current event.
    entries.append((channel_id, now, content_hash))
    
    # Cap entries per user to prevent unbounded growth
    max_entries = rate_threshold * 2
    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    _tracker[user_id] = entries

    unique_channels = {ch for ch, _, _ in entries}
    if len(unique_channels) >= rate_threshold:
        return True

    # Same content in 2+ channels.
    content_channels = {ch for ch, _, ct in entries if ct == content_hash}
    if len(content_channels) >= 2:
        return True

    return False


def clear_user(user_id: int) -> None:
    """Clear tracking state for a user (e.g. after they are punished)."""
    _tracker.pop(user_id, None)
