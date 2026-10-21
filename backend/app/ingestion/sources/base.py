"""Базовый интерфейс источника новостей. Новый источник = новый файл с подклассом (критерий 07)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawNews:
    source: str
    url: str
    title: str
    body: str
    published_at: datetime


class NewsSource(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[RawNews]:
        ...
