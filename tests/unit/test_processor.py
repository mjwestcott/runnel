import pytest

from runnel.exceptions import Misconfigured


@pytest.mark.asyncio
async def test_name(app, stream):
    @app.processor(stream)
    async def foo(events):
        pass

    with pytest.raises(Misconfigured):
        # Has the same name -- error.
        @app.processor(stream)
        async def foo(events):  # noqa: F811
            pass

    # Different given name -- fine.
    @app.processor(stream, name="newfoo")
    async def foo(events):  # noqa: F811
        pass

    assert foo.name == "newfoo"
    assert foo.id == f"{app.name}.{stream.name}.newfoo"
