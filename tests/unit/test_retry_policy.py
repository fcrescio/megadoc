from common.application.retry import retry_delay_seconds


def test_retry_delay_is_deterministic_jittered_and_capped():
    first = retry_delay_seconds(0, key="job-a")
    second = retry_delay_seconds(1, key="job-a")

    assert first == retry_delay_seconds(0, key="job-a")
    assert 48 <= first <= 72
    assert 96 <= second <= 144
    assert retry_delay_seconds(20, key="job-a") <= 900
    assert retry_delay_seconds(0, key="job-a") != retry_delay_seconds(0, key="job-b")
