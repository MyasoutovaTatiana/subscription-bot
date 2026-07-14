"""Central Bank of Russia XML daily rates provider."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from app.services.exchange_rates.base import ExchangeRateProvider, RateQuote

logger = logging.getLogger(__name__)

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


class CbrExchangeRateProvider(ExchangeRateProvider):
    """Loads official CBR daily XML rates."""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 15.0) -> None:
        self._external_client = client
        self._timeout = timeout

    async def fetch_rates(self, on_date: date) -> list[RateQuote]:
        last_error: Exception | None = None
        for offset in range(0, 10):
            day = on_date - timedelta(days=offset)
            try:
                quotes = await self._fetch_for_day(day)
                if quotes:
                    return quotes
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("CBR fetch failed for %s: %s", day, exc)
        if last_error:
            logger.error("CBR unavailable for %s: %s", on_date, last_error)
        return []

    async def _fetch_for_day(self, day: date) -> list[RateQuote]:
        params = {"date_req": day.strftime("%d/%m/%Y")}
        if self._external_client is not None:
            response = await self._external_client.get(CBR_URL, params=params)
            response.raise_for_status()
            return self._parse_xml(response.content, fallback_date=day)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(CBR_URL, params=params)
            response.raise_for_status()
            return self._parse_xml(response.content, fallback_date=day)

    @staticmethod
    def _parse_xml(content: bytes, *, fallback_date: date) -> list[RateQuote]:
        root = ElementTree.fromstring(content)
        date_attr = root.attrib.get("Date")
        if date_attr:
            day, month, year = date_attr.split(".")
            rate_date = date(int(year), int(month), int(day))
        else:
            rate_date = fallback_date

        quotes: list[RateQuote] = []
        for valute in root.findall("Valute"):
            char_code = (valute.findtext("CharCode") or "").strip().upper()
            nominal_text = (valute.findtext("Nominal") or "1").strip()
            value_text = (valute.findtext("Value") or "").strip().replace(",", ".")
            if not char_code or not value_text:
                continue
            nominal = int(nominal_text)
            value_rub = Decimal(value_text)
            unit = value_rub / Decimal(nominal)
            quotes.append(
                RateQuote(
                    currency=char_code,
                    rate_date=rate_date,
                    nominal=nominal,
                    value_rub=value_rub,
                    unit_rate_rub=unit,
                    source="cbr",
                )
            )
        return quotes
