import asyncio

import pytest

from src.openai_client import OpenAIClient, CommentaryResult, AttributionOverviewResult


def test_make_request_respects_cancel_event_before_post():
    client = OpenAIClient(api_key="test-key")
    cancel_event = asyncio.Event()
    cancel_event.set()

    async def _post(*_args, **_kwargs):
        raise AssertionError("post should not be called when cancelled")

    async def _run():
        async with DummyAsyncClient(post=_post) as http_client:
            await client._make_request(
                http_client,
                prompt="test",
                use_web_search=False,
                cancel_event=cancel_event,
            )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


def test_poll_response_status_respects_cancel_event():
    client = OpenAIClient(api_key="test-key")
    cancel_event = asyncio.Event()
    cancel_event.set()

    async def _get(*_args, **_kwargs):
        raise AssertionError("get should not be called when cancelled")

    async def _run():
        async with DummyAsyncClient(get=_get) as http_client:
            await client._poll_response_status(
                client=http_client,
                response_id="resp_123",
                headers={},
                max_wait=10.0,
                cancel_event=cancel_event,
            )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


def test_generate_commentary_batch_raises_cancelled_error_when_cancelled(monkeypatch):
    client = OpenAIClient(api_key="test-key")
    cancel_event = asyncio.Event()

    async def _fake_generate_commentary(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return CommentaryResult(
            ticker="AAA",
            security_name="Test Co",
            commentary="ok",
            citations=[],
            success=True,
        )

    monkeypatch.setattr(client, "generate_commentary", _fake_generate_commentary)

    requests = [
        {"ticker": "AAA", "security_name": "Test Co", "prompt": "p", "portcode": "P1"},
        {"ticker": "BBB", "security_name": "Other Co", "prompt": "p", "portcode": "P1"},
    ]

    async def _run():
        async def _trigger_cancel():
            await asyncio.sleep(0.01)
            cancel_event.set()

        asyncio.create_task(_trigger_cancel())
        await client.generate_commentary_batch(
            requests,
            use_web_search=False,
            cancel_event=cancel_event,
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


def test_generate_attribution_overview_batch_raises_cancelled_error_when_cancelled(monkeypatch):
    client = OpenAIClient(api_key="test-key")
    cancel_event = asyncio.Event()

    async def _fake_generate_attribution_overview(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return AttributionOverviewResult(
            portcode="P1",
            output="overview",
            citations=[],
            success=True,
        )

    monkeypatch.setattr(client, "generate_attribution_overview", _fake_generate_attribution_overview)

    requests = [
        {"portcode": "P1", "prompt": "p1"},
        {"portcode": "P2", "prompt": "p2"},
    ]

    async def _run():
        async def _trigger_cancel():
            await asyncio.sleep(0.01)
            cancel_event.set()

        asyncio.create_task(_trigger_cancel())
        await client.generate_attribution_overview_batch(
            requests,
            use_web_search=False,
            cancel_event=cancel_event,
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


def test_generate_attribution_overview_requires_citations(monkeypatch):
    client = OpenAIClient(api_key="test-key")

    async def _fake_make_request(*_args, **_kwargs):
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Attribution summary without citations.",
                            "annotations": [],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(client, "_make_request", _fake_make_request)

    async def _run():
        return await client.generate_attribution_overview(
            portcode="PORT1",
            prompt="test prompt",
            use_web_search=False,
            require_citations=True,
        )

    result = asyncio.run(_run())
    assert result.success is False
    assert "No citations found" in result.error_message


def test_generate_attribution_overview_batch_maps_results_by_portcode(monkeypatch):
    client = OpenAIClient(api_key="test-key")

    async def _fake_generate_attribution_overview(*_args, **kwargs):
        return AttributionOverviewResult(
            portcode=kwargs["portcode"],
            output=f"overview-{kwargs['portcode']}",
            citations=[],
            success=True,
        )

    monkeypatch.setattr(client, "generate_attribution_overview", _fake_generate_attribution_overview)

    requests = [
        {"portcode": "PORT1", "prompt": "p1"},
        {"portcode": "PORT2", "prompt": "p2"},
    ]

    async def _run():
        return await client.generate_attribution_overview_batch(
            requests,
            use_web_search=False,
            require_citations=False,
        )

    results = asyncio.run(_run())
    assert [r.portcode for r in results] == ["PORT1", "PORT2"]
    assert results[0].output == "overview-PORT1"
    assert results[1].output == "overview-PORT2"


def test_reasoning_levels_for_model():
    assert OpenAIClient._reasoning_levels_for_model("gpt-5.2-2025-12-11") == [
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert OpenAIClient._reasoning_levels_for_model("gpt-5.2-pro-2025-12-11") == [
        "medium",
        "high",
        "xhigh",
    ]
    assert OpenAIClient._reasoning_levels_for_model("gpt-5-nano-2025-08-07") == [
        "low",
        "medium",
        "high",
    ]


def test_normalize_thinking_level():
    client = OpenAIClient(api_key="test-key", model="gpt-5.2-2025-12-11")

    assert client._normalize_thinking_level("gpt-5.2-2025-12-11", "none") == "none"
    assert client._normalize_thinking_level("gpt-5.2-2025-12-11", "invalid") == "none"
    assert client._normalize_thinking_level("gpt-5.2-pro-2025-12-11", "none") == "medium"
    assert client._normalize_thinking_level("gpt-5-nano-2025-08-07", "xhigh") == "medium"


class DummyAsyncClient:
    def __init__(self, post=None, get=None):
        self._post = post
        self._get = get

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        if self._post is None:
            raise AssertionError("post not configured")
        return await self._post(*args, **kwargs)

    async def get(self, *args, **kwargs):
        if self._get is None:
            raise AssertionError("get not configured")
        return await self._get(*args, **kwargs)
