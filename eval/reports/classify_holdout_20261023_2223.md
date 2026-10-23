# Оценка разметки новостей (Gemma) на отложенном наборе реальных новостей

Новостей: 49 (деловых по эталону: 46), теги сравниваются на 46 новостях, которые деловыми считают и эталон, и модель. Эталон размечен вслепую (`eval/golden_classify_holdout.jsonl`), разметка модели - как её записал конвейер (`eval/fixtures/news_holdout.jsonl`). Не размечены конвейером (перепечатка или сбой разметки): 1 ['daf91115399476b1'].

| Что | Precision | Recall | F1 | Эталонных меток |
|---|---|---|---|---|
| Фильтр «про бизнес» (класс: деловая) | 1.0 | 1.0 | 1.0 | 46 |
| Факторы (набор) | 0.626 | 0.859 | 0.724 | 78 |
| Отрасли ОКВЭД2 | 0.64 | 0.727 | 0.681 | 44 |
| Страны | 0.913 | 0.84 | 0.875 | 25 |

- Точность фильтра: 1.0; отброшено деловых новостей: 0, пропущено неделовых: 0.
- Главный фактор совпал с эталонным: 0.682; главный фактор модели есть среди эталонных: 0.891.
- Чаще всего пропущены факторы: [('key_rate', 2), ('inflation', 2), ('gdp_growth', 2), ('sanctions_trade', 1), ('logistics', 1)]; лишние: [('company_event', 8), ('consumption', 8), ('regulation', 8), ('taxes', 3), ('gdp_growth', 3)].
- Отрасли: пропущены [('06', 3), ('19', 1), ('26', 1), ('73', 1), ('68', 1)]; лишние [('64', 3), ('01', 3), ('68', 2), ('35', 2), ('62', 2)].

## Расхождения с эталоном

- 89a2912c45cd43ef Финансовые инструменты открывают новые возможности для МСП: эталон {'business': True, 'factors': ['regulation']}, модель {'business': True, 'factors': ['regulation', 'company_event']}
- 4561da70fb38b4fe Андрей Воронцов: Минфин России вместе с профильными ведомствами прорабатывает поправки в з: эталон {'business': True, 'factors': ['regulation']}, модель {'business': True, 'factors': ['regulation', 'logistics']}
- 64910c01b1493bb8 Антон Силуанов обозначил ключевые задачи для мировой экономики: эталон {'business': True, 'factors': ['gdp_growth', 'oil_gas']}, модель {'business': True, 'factors': ['oil_gas', 'consumption', 'bonds', 'gdp_growth']}
- bf7fc7d48b1c24b0 Более 80 млрд рублей кредитов с господдержкой привлечет малый и средний бизнес в 4 квартал: эталон {'business': True, 'factors': ['key_rate']}, модель {'business': True, 'factors': ['consumption', 'company_event']}
- 052da90654a6850a Международное налоговое сотрудничество обсудили в Бангкоке: эталон {'business': True, 'factors': ['taxes']}, модель {'business': True, 'factors': ['taxes', 'regulation']}
- fdad0469c1574659 Число индивидуальных инвестиционных счетов достигло 6,7 млн, а объем средств на них превыс: эталон {'business': True, 'factors': []}, модель {'business': True, 'factors': ['bonds', 'consumption', 'key_rate']}
- 70d7658de650c89c ПИСЬМЕННОЕ ЗАЯВЛЕНИЕ Министра финансов Российской Федерации, Управляющего МВФ от Российско: эталон {'business': True, 'factors': ['gdp_growth', 'oil_gas', 'bonds', 'inflation']}, модель {'business': True, 'factors': ['gdp_growth', 'bonds', 'oil_gas', 'regulation']}
- c9ea10287d9407b6 Комитет Госдумы одобрил отвязку МРОТ от медианной зарплаты: эталон {'business': True, 'factors': ['labor', 'regulation', 'real_estate']}, модель {'business': True, 'factors': ['labor', 'regulation', 'real_estate', 'taxes']}
- d939f798ba2f4ea4 Экономист Михаил Задорнов дал совет, куда вложить ₽1 млн: эталон {'business': True, 'factors': ['bonds', 'key_rate']}, модель {'business': True, 'factors': ['key_rate', 'inflation', 'bonds', 'company_event']}
- 11484611400f9ff7 Михаил Задорнов назвал объективный курс рубля на текущий момент: эталон {'business': True, 'factors': ['fx', 'sanctions_trade']}, модель {'business': True, 'factors': ['fx', 'company_event']}
- d27d32b9555618cc Рынок акций подскочил на новостях о прекращении огня в Алешках: эталон {'business': True, 'factors': ['sanctions_trade', 'oil_gas']}, модель {'business': True, 'factors': ['sanctions_trade', 'oil_gas', 'company_event']}
- 47425fee5e93b461 Ведев оценил, ждать ли «приятного сюрприза» от ЦБ в конце года: эталон {'business': True, 'factors': ['key_rate', 'gdp_growth']}, модель {'business': True, 'factors': ['key_rate']}
- c23e77250f9ae64a Глава Nvidia предсказал Казахстану роль центра ИИ для Европы: эталон {'business': True, 'factors': ['company_event', 'energy']}, модель {'business': True, 'factors': ['energy', 'company_event', 'sanctions_trade']}
- 478940a7edcd60dd ЦБ опустил официальный курс доллара ниже ₽81 впервые с августа: эталон {'business': True, 'factors': ['fx', 'key_rate']}, модель {'business': True, 'factors': ['fx', 'key_rate', 'inflation', 'oil_gas']}
- 829bb387910a9d5b «Яндекс» восстановил доступ более чем к 90% данных клиентов Yandex Cloud: эталон {'business': True, 'factors': ['company_event']}, модель {'business': True, 'factors': ['company_event', 'regulation']}
- 5b6ba6225cb97a80 "Битва за внимание": короткие видео убивают Netflix, пишут СМИ: эталон {'business': True, 'factors': ['company_event', 'consumption']}, модель {'business': True, 'factors': ['consumption', 'company_event']}
- af457d663b96428a Стартовал третий Всероссийский рейтинг отелей для деловых мероприятий: эталон {'business': True, 'factors': []}, модель {'business': True, 'factors': ['company_event']}
- e9c7f7a1d517fa2f Mercedes-Benz планирует сократить несколько тысяч временных работников: эталон {'business': True, 'factors': ['company_event', 'labor']}, модель {'business': True, 'factors': ['labor', 'company_event']}
- 903b711300248e1c "АвтоВАЗ" субсидирует ставки по кредитам на ряд моделей автомобилей: эталон {'business': True, 'factors': ['company_event', 'consumption', 'key_rate']}, модель {'business': True, 'factors': ['consumption', 'company_event']}
- 9aedae838d729659 "АвтоВАЗ" допускает незначительное снижение продаж Lada в октябре: эталон {'business': True, 'factors': ['company_event', 'consumption']}, модель {'business': True, 'factors': ['consumption', 'company_event']}
- 7e0d94978ca10d7d Axios: авиабилеты в США могут остаться дорогими даже при дешевом топливе: эталон {'business': True, 'factors': ['logistics', 'inflation', 'oil_gas']}, модель {'business': True, 'factors': ['consumption', 'oil_gas', 'company_event']}
- 54480b029aebac4b Суд объявил перерыв в слушаниях по долгу "Гугла": эталон {'business': True, 'factors': ['company_event']}, модель {'business': True, 'factors': ['company_event', 'regulation']}
- 70f58df0739ff8e0 Парламенты Юга России попросят федеральное правительство дерегулировать бизнес: эталон {'business': True, 'factors': ['regulation']}, модель {'business': True, 'factors': ['regulation', 'gdp_growth', 'taxes']}
- 52940eff731d5e09 Силуанов о бюджете: нужно жить экономнее, но без затягивания поясов: эталон {'business': True, 'factors': ['taxes']}, модель {'business': True, 'factors': ['taxes', 'gdp_growth']}
- 1d917624da0850f0 Риелторы попросили Генпрокуратуру проверить отказы СФР по маткапиталу: эталон {'business': True, 'factors': ['real_estate', 'regulation']}, модель {'business': True, 'factors': ['regulation', 'real_estate']}
- 95c9e2a00a5f4f8e ФНС анонсировала переходный налоговый спецрежим для самозанятых: эталон {'business': True, 'factors': ['taxes']}, модель {'business': True, 'factors': ['taxes', 'regulation']}
- e68cbd64fbbb1e93 Бумажный НДС с реальным риском // На форуме ТПП обсудили практику борьбы со схемами налого: эталон {'business': True, 'factors': ['taxes']}, модель {'business': True, 'factors': ['taxes', 'regulation']}
- 6df50ba93e098d61 «Русснефть» получила рассрочку на уплату задолженности в 10 млрд рублей: эталон {'business': True, 'factors': ['company_event', 'oil_gas', 'taxes']}, модель {'business': True, 'factors': ['taxes', 'company_event', 'oil_gas', 'gdp_growth']}
- c14186fd7ff83028 Нефть марки Brent превысила $116 впервые с марта: эталон {'business': True, 'factors': ['oil_gas']}, модель {'business': True, 'factors': ['oil_gas', 'sanctions_trade']}
- 54369d2c95bd6301 «АвтоВАЗ» спрогнозировал снижение продаж новых Lada в октябре: эталон {'business': True, 'factors': ['company_event', 'consumption']}, модель {'business': True, 'factors': ['consumption', 'company_event']}
- 62be49a05c7e5d6b Алиханов: выпуск легковых авто в России вырос более чем на 27% за девять месяцев: эталон {'business': True, 'factors': ['gdp_growth']}, модель {'business': True, 'factors': ['gdp_growth', 'consumption']}
- 9f0560a483a6f280 Никитин: около 100 иностранных судов перешли под флаг России с июня: эталон {'business': True, 'factors': ['logistics', 'regulation']}, модель {'business': True, 'factors': ['logistics']}
- 297c04863ec3d3ad ФАС заподозрила «Пятерочку» в дискриминации воронежского производителя молока: эталон {'business': True, 'factors': ['company_event', 'regulation']}, модель {'business': True, 'factors': ['regulation', 'consumption']}
- afae82f53ee1cfd3 Кредитный портфель Т-банка растет за счет корпоративных кредитов // Чистая прибыль Т-банка: эталон {'business': True, 'factors': ['company_event']}, модель {'business': True, 'factors': ['company_event', 'consumption']}
- 714d65408703afd2 Мустафаев: Россия вложила более $10 млрд в экономику Азербайджана: эталон {'business': True, 'factors': ['sanctions_trade']}, модель {'business': True, 'factors': ['sanctions_trade', 'taxes']}
- 8edc62185a4daf85 Частные инвестиции в городские ГЧП и концессии превысили 1 трлн рублей: эталон {'business': True, 'factors': ['gdp_growth', 'energy']}, модель {'business': True, 'factors': ['consumption', 'energy', 'logistics']}
- ad46a2a161001028 Владельцы ПВЗ попросили не облагать налогом кадастровую стоимость их помещений: эталон {'business': True, 'factors': ['taxes', 'real_estate']}, модель {'business': True, 'factors': ['taxes', 'regulation']}
- 7ae0da9eeb8003ca Как власти хотят изменить инвестиционный режим на Дальнем Востоке и в Арктике: эталон {'business': True, 'factors': ['regulation']}, модель {'business': True, 'factors': ['regulation', 'company_event']}
- 3e04ea298f6a2f2e Минпромторг предложил отсрочить уплату утильсбора для автопроизводителей: эталон {'business': True, 'factors': ['taxes']}, модель {'business': True, 'factors': ['taxes', 'regulation']}