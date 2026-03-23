from __future__ import annotations

from typing import Protocol

from btc_exchange_intel_agent.models import AddressAttribution


class Provider(Protocol):
    name: str

    async def collect(self) -> list[AddressAttribution]:
        ...
