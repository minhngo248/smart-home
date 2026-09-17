"""Run the HTTP and voice API."""

import asyncio
import logging
import os
import signal

import uvicorn

from api import app
from home import Home, HomeService
from tapo_control import parse_args, required_environment


async def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    home = HomeService(Home.from_environment(), required_environment("TAPO_USER"),
                       required_environment("TAPO_PASS"))
    app.state.home = home
    server = uvicorn.Server(uvicorn.Config(
        app, host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")), timeout_graceful_shutdown=15,
    ))
    api_task = None
    stop_task = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        api_task = asyncio.create_task(asyncio.to_thread(server.run))
        stop_task = asyncio.create_task(stop.wait())
        await asyncio.wait([api_task, stop_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        server.should_exit = True
        try:
            if api_task is not None:
                await api_task
        finally:
            if stop_task is not None:
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
            await asyncio.gather(*(c.disconnect() for c in home.controllers.values()),
                                 return_exceptions=True)
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)


if __name__ == "__main__":
    asyncio.run(main())
