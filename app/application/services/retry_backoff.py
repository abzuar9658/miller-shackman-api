from datetime import timedelta


def exponential_retry_delay(
    attempt_count: int,
    *,
    base_delay: timedelta,
    max_delay: timedelta,
) -> timedelta:
    multiplier = 2 ** max(attempt_count - 1, 0)
    delay = timedelta(seconds=base_delay.total_seconds() * multiplier)
    if delay > max_delay:
        return max_delay
    return delay
