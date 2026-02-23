from contextlib import contextmanager
from typing import TYPE_CHECKING
from contextvars import ContextVar, Token

if TYPE_CHECKING:
    from package.apps import App


warnings_ctx: "ContextVar[list[tuple[App, str]]]" = ContextVar("warnings")
app_ctx: "ContextVar[App]" = ContextVar("app")


def make_warnings_ctx() -> "Token":
    return warnings_ctx.set([])


def reset_warnings_ctx(token: "Token"):
    return warnings_ctx.reset(token)


@contextmanager
def app_context(app: "App"):
    t = app_ctx.set(app)
    try:
        yield
    finally:
        app_ctx.reset(t)


def log_warning(message: str):
    if (warnings := warnings_ctx.get()) is not None and (app := app_ctx.get()) is not None:
        if next(filter(lambda w: w[0].key == app.key and w[1] == message, warnings), None) is None:
            warnings.append((app, message))


def print_warnings():
    if (warnings := warnings_ctx.get()) is not None:
        for app, message in warnings:
            print(f"Warning - {app.identifier}: {message}")
