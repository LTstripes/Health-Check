"""Request-local /brief timings; never retain SQL text, parameters or health values."""

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import event

from healthcheck.logging import log_event


@dataclass
class BlockTiming:
    milliseconds: float = 0
    sql_milliseconds: float = 0
    sql_count: int = 0


class BriefTiming:
    def __init__(self):
        self.blocks: dict[str, BlockTiming] = {}
        self.active: BlockTiming | None = None

    @contextmanager
    def block(self, name):
        timing = self.blocks.setdefault(name, BlockTiming())
        previous, self.active = self.active, timing
        started = perf_counter()
        try:
            yield
        finally:
            timing.milliseconds += (perf_counter() - started) * 1000
            self.active = previous

    @contextmanager
    def sql(self, connection):
        # Connection listeners are removed before returning the pooled connection.
        # Concurrent requests on other connections cannot contaminate these counts.
        started = 0.0

        def before(conn, cursor, statement, parameters, context, executemany):
            nonlocal started
            started = perf_counter()
            if self.active is not None:
                self.active.sql_count += 1

        def after(conn, cursor, statement, parameters, context, executemany):
            if self.active is not None:
                self.active.sql_milliseconds += (perf_counter() - started) * 1000

        event.listen(connection, "before_cursor_execute", before)
        event.listen(connection, "after_cursor_execute", after)
        try:
            yield
        finally:
            event.remove(connection, "before_cursor_execute", before)
            event.remove(connection, "after_cursor_execute", after)

    def finish(self, response, *, debug_log=False):
        metrics = []
        for name, timing in self.blocks.items():
            metrics.extend((
                f"{name};dur={timing.milliseconds:.3f}",
                f"{name}_sql;dur={timing.sql_milliseconds:.3f}",
                f'{name}_queries;desc="{timing.sql_count}"',
            ))
        response.headers["Server-Timing"] = ", ".join(metrics)
        if debug_log:
            log_event("brief_timing", operation="brief", reason=", ".join(metrics))
        return response
