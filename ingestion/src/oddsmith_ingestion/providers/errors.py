class ProviderError(Exception):
    """A provider call failed and should not be retried as-is."""


class RetryableError(ProviderError):
    """Transient failure (429, 5xx, network). The client retries these."""


class QuotaExhausted(ProviderError):
    """Daily requests or credits are used up, or at the configured reserve."""
