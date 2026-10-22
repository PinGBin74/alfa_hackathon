"""Реестр источников новостей (перечислены в THIRD_PARTY_NOTICES.md).

Проверено 21.10.2026: каждая лента отдаёт записи с датами публикации, полный текст берётся из ленты
(РБК, пресс-релизы ЦБ) или со страницы через trafilatura. cbr.ru, minfin.gov.ru и страницы rbc.ru
отказывают зарубежному прокси - `Http` в этом случае ходит напрямую.
Порядок важен: в одном запуске первоисточник (ЦБ, Минфин) обрабатывается раньше перепечаток.
ТАСС не подключён: страницы статей закрыты JS-проверкой, в ленте только однострочный анонс.
"""
from app.ingestion.sources.base import NewsSource
from app.ingestion.sources.rss import RssSource

RBC_BUSINESS = ("Экономика", "Бизнес", "Финансы", "Инвестиции", "Недвижимость", "Технологии и медиа")

SOURCES: list[NewsSource] = [
    RssSource("Банк России", "https://www.cbr.ru/rss/RssPress", extract=False),
    RssSource("Минфин России", "https://minfin.gov.ru/rss_news?mod=news&lim=50"),
    RssSource("Интерфакс", "https://www.interfax.ru/rss", categories=("Экономика",)),
    RssSource("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", categories=RBC_BUSINESS,
              full_text_field="rbc_news_full-text"),
    RssSource("ПРАЙМ", "https://1prime.ru/export/rss2/business/index.xml"),
    RssSource("Коммерсантъ", "https://www.kommersant.ru/rss/section-economics.xml"),
    RssSource("Коммерсантъ", "https://www.kommersant.ru/rss/section-business.xml"),
    RssSource("Ведомости", "https://www.vedomosti.ru/rss/rubric/economics"),
]
