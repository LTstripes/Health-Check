# Project Wiki

Срез: **8 ноября 2026**, код `fbab16c1229f4362a7a7e42e2ca9fd73c3113ee5`.
Статусы ниже перенесены из последних записанных результатов; GitHub и установленный
runtime при этом редактировании не проверялись. Это статус, не разрешение на запуск.
[Vision](PRODUCT_VISION.md) — назначение; [Architecture](ARCHITECTURE.md) — контракты;
[Development](DEVELOPMENT_PROCESS.md) и [Operations](OWNER_OPERATIONS.md) — процедуры.

<a id="current-canonical-state"></a>
## Есть

- Xiaomi Home/S400: импорт скриншотов, оригиналы, кандидаты/подтверждение,
  исправления и история веса/состава тела с разделением методов; openScale —
  отдельный совместимый вход ([#229](https://github.com/LTstripes/Health-Check/issues/229),
  [#240](https://github.com/LTstripes/Health-Check/issues/240)).
- Garmin/Google: сохранённые типизированные данные, ограниченные sync/backfill,
  история исправлений, диагностика источников. Отдельно реализованы
  [Google Steps](GOOGLE_STEPS_ACQUISITION.md) и [exercise import](GOOGLE_EXERCISE_IMPORT.md).
- Экраны Обзор, Вес, Сон, Статистика, Активность, Данные и Комментарии;
  источники/даты, 7/30-дневный сон и вариативность, сравнение занятий, Garmin Steps
  all-time и отдельные Google Steps; целочисленное отображение средних Steps
  ([#537](https://github.com/LTstripes/Health-Check/pull/537),
  [#549](https://github.com/LTstripes/Health-Check/pull/549)).
- Комментарии с ревизиями и явным временем/IANA; описательные сравнения с ближайшим
  сном, круговая регулярность и выбранные event/revision в экспорте
  ([#468](https://github.com/LTstripes/Health-Check/pull/468),
  [#539](https://github.com/LTstripes/Health-Check/pull/539)).
- Локальный приём лабораторного PDF/структурированной транскрипции, review,
  подтверждение и ревизии ([#348](https://github.com/LTstripes/Health-Check/issues/348#issuecomment-6446273624));
  этот результат не устанавливает факт долговременного импорта в Stable.
- Аналитические JSON/text/compact выгрузки и MCP-адаптер 7/30 дней; фактическое
  аутентифицированное подключение ChatGPT ещё не подтверждено
  ([#543](https://github.com/LTstripes/Health-Check/pull/543)).
- Еженедельный дайджест доставляется внешней автоматизацией по воскресеньям
  в **20:00 МСК**, первая доставка **25.10.2026**
  ([результат #488](https://github.com/LTstripes/Health-Check/issues/488#issuecomment-6434398400)).
- Настраиваемый календарный пояс владельца `HEALTHCHECK_OWNER_TIMEZONE`, по умолчанию
  Europe/Moscow ([#556](https://github.com/LTstripes/Health-Check/pull/556)).

## Дальше

- Измеренный проход по плотности/отступам [#515](https://github.com/LTstripes/Health-Check/issues/515);
  общая продуктовая редакция после дизайн-PR [#552](https://github.com/LTstripes/Health-Check/pull/552).
- История/длинные периоды [#380](https://github.com/LTstripes/Health-Check/issues/380),
  доактивационная история Google Steps [#522](https://github.com/LTstripes/Health-Check/issues/522).
  Годовой Sleep range-reader остаётся на техническом HOLD после таймаутов;
  готовность Garmin all-time не означает готовность этого чтения.
- Более широкие Context/recovery/workout-анализы и отдельные проверки реальных
  данных [#462](https://github.com/LTstripes/Health-Check/issues/462)/[#464](https://github.com/LTstripes/Health-Check/issues/464),
  оставшаяся Owner UAT Комментариев/карточек восстановления и прямого подключения.
- Активные ккал [#319](https://github.com/LTstripes/Health-Check/issues/319):
  принятый `session_total_calories` — общий native total с неизвестной единицей,
  а не доказанные активные ккал. Recovery Time unit/producer также остаются неизвестными.
- Месячные/годовые обзоры, последующая лабораторная аналитика и отдельные
  medication/supplement-сценарии; они не следуют автоматически из готового intake.

## Установлено

Последний записанный Owner-local отчёт от **06.11.2026**: Stable **`1831b1ee`**,
schema **`0020_google_exercise`**, после [#544](https://github.com/LTstripes/Health-Check/pull/544)/[#549](https://github.com/LTstripes/Health-Check/pull/549);
это датированное сообщение владельца, не свежая проверка установленного кода.

<a id="history"></a>
## История

R00–R10, прошлые SHA/CI/UAT и журналы выполнения остаются в
[предыдущей Wiki](https://github.com/LTstripes/Health-Check/blob/fbab16c1229f4362a7a7e42e2ca9fd73c3113ee5/docs/PROJECT_WIKI.md),
issues/PR и [выпуске v0.1.0](https://github.com/LTstripes/Health-Check/releases/tag/v0.1.0).
Текущие назначения проверяются отдельно; эта страница не запускает backlog.
