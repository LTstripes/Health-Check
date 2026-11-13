"""Synthetic-only current confirmed analyte history and desktop entry points."""

import copy
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from healthcheck.config import Settings
from healthcheck.db.engine import session_scope
from healthcheck.db.models import RawArtifact
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.labs.history import analyte_key, normalized_name, unit_key
from healthcheck.labs.models import LabInterpretation
from healthcheck.web.labs import analyte_groups, history_chart
from healthcheck.web.ui_app import create_ui_app
from test_lab_intake import BASE, confirm, draft, raw, synthetic_pdf
from test_lab_intake import runtime as runtime


def add(service, tag, *, name="Маркер", unit="мг/л", result="<5", date=None,
        printed=None, accepted=True, extra=None):
    pdf = synthetic_pdf(tag)
    value = draft(pdf)
    value.update(result_date=date, printed_date=printed)
    row = value["rows"][0]
    row.update(label_raw=name, unit_raw=unit, result_raw=result, decimal="5",
               reference_raw=f"Референс {tag}", flag_raw="↑")
    value["rows"] = [row]
    if extra:
        value["rows"].append({**copy.deepcopy(row), **extra, "row_id": "r2"})
    receipt = service.stage(pdf, raw(value), f"stage-{tag}")
    if accepted:
        confirm(service, receipt, operation=f"confirm-{tag}", selected=["r1"], partial=bool(extra))
    return receipt, value, pdf


def client_for(paths):
    app, _ = create_ui_app(
        Settings(data_dir=paths.root), photo_extractor=FakeImageMeasurementExtractor()
    )
    return TestClient(app, base_url=BASE)


def test_confirmed_history_grouping_literal_values_dates_and_pdf(runtime):
    service, paths = runtime
    old, _, old_pdf = add(service, "old", result="< 5,0000",
                          date={"value": "2099-01-02", "precision": "date"})
    new, _, _ = add(service, "new", name="  МАРКЕР. ", unit=" МГ/Л ", result="<5",
                     date={"value": "2099-03-04T10:11:12+03:00", "precision": "second"},
                     printed={"value": "2099-12-31", "precision": "date"})
    add(service, "printed", printed={"value": "2099-02-03T09:30", "precision": "minute"})
    add(service, "different", unit="ммоль/л", date={"value": "2099-01-01", "precision": "date"})
    add(service, "undated", unit=None)
    add(service, "synonym", name="Другой маркер")
    pending, _, _ = add(service, "pending", result="UNCONFIRMED SECRET", accepted=False)
    before = service.reports()
    item = next(i for i in service.analytes()["analytes"] if i["key"] == analyte_key("Маркер"))
    assert item["count"] == 5 and item["draft_count"] == 1
    assert [len(g["rows"]) for g in item["groups"]] == [3, 1, 1]
    assert item["latest"]["report"]["report_id"] == new["report_id"]
    assert item["latest"]["row"]["unit_raw"] == " МГ/Л "
    with client_for(paths) as client:
        response = client.get(f'/labs/analytes/{item["key"]}')
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        page = response.text
        assert "5 результатов" in page and "ещё 1 в черновиках" in page
        assert page.count("data-lab-unit-group") == 3
        assert "Другая единица: ммоль/л — не сравнивается автоматически" in page
        assert "&lt; 5,0000" in page and "&lt;5" in page
        assert "4 марта 2099, 10:11" in page and "точность до секунды" in page
        assert "3 февраля 2099, 09:30" in page and "дата печати · точность до минуты" in page
        assert "2 января 2099" in page and "точность до дня" in page
        assert "31.12.2099" not in page
        assert "Референс old" in page and "Референс new" in page and "↑" in page
        assert "Synthetic Clinic" in page and "Synthetic Lab" in page
        assert "UNCONFIRMED SECRET" not in page and pending["report_id"] not in page
        assert "Другой маркер" not in page
        assert f'/labs/{old["report_id"]}/original' in page
        assert client.get(f'/labs/{old["report_id"]}/original').content == old_pdf
        assert '<details class="lab-history-meta">' in page and '<details open' not in page
        index = client.get("/labs").text
        assert index.index('id="lab-analytes-heading"') < index.index('id="lab-reports-heading"')
        assert f'href="/labs/analytes/{item["key"]}"' in index
        review = client.get(f'/labs/review/{old["interpretation_id"]}').text
        assert f'href="/labs/analytes/{item["key"]}"' in review
    assert service.reports() == before  # GET projections do not change stored state.


def test_partial_current_snapshot_revise_and_draft_only_empty_state(runtime):
    service, paths = runtime
    item, value, pdf = add(service, "partial", extra={"label_raw": "Только черновик"})
    listing = {i["key"]: i for i in service.analytes()["analytes"]}
    draft_key = analyte_key("Только черновик")
    assert listing[draft_key]["count"] == 0 and listing[draft_key]["draft_count"] == 1
    with client_for(paths) as client:
        empty = client.get(f"/labs/analytes/{draft_key}")
        assert empty.status_code == 200
        assert "Подтверждённых результатов по этому показателю нет" in empty.text
        assert "ещё 1 в черновиках" in empty.text
        assert f'/labs/analytes/{draft_key}' not in client.get("/labs").text
        review = client.get(f'/labs/review/{item["interpretation_id"]}').text
        assert f'/labs/analytes/{draft_key}' not in review
        assert client.get("/labs/analytes/unknown").status_code == 404
        assert "Подтверждённых результатов по этому показателю нет" in client.get(
            "/labs/analytes/unknown"
        ).text
    head = service.review(item["interpretation_id"])["expected_head"]
    value["rows"] = [value["rows"][1]]
    next_item = service.stage(pdf, raw(value), "revised-draft")
    pending = {i["key"]: i for i in service.analytes()["analytes"]}
    assert pending[analyte_key("Маркер")]["count"] == 1
    assert pending[draft_key]["count"] == 0 and pending[draft_key]["draft_count"] == 2
    confirm(service, next_item, operation="revised", selected=["r2"], head=head, kind="revise")
    histories = service.analytes()["analytes"]
    assert len(histories) == 1 and histories[0]["key"] == draft_key
    assert histories[0]["count"] == 1 and histories[0]["draft_count"] == 0


def test_escaping_unknown_fields_qualitative_and_unreadable_drafts(runtime):
    service, paths = runtime
    name = '<script>alert("x")</script>'
    _, value, pdf = add(service, "escape", name=name, unit=None, accepted=False)
    value["rows"][0].update(result_raw="<qualitative & raw>", decimal=None, comparator=None,
                             value_kind="unparsed", flag_raw=None, reference_raw=None)
    receipt = service.stage(pdf, raw(value), "escape-corrected")
    confirm(service, receipt, selected=["r1"])
    broken, _, _ = add(service, "broken", accepted=False)
    with session_scope(service.engine) as session:
        interpretation = session.get(LabInterpretation, broken["interpretation_id"])
        artifact = session.get(RawArtifact, interpretation.draft_artifact_id)
        (paths.root / "artifacts" / artifact.relative_storage_path).write_bytes(b"corrupt")
    with client_for(paths) as client:
        page = client.get(f"/labs/analytes/{analyte_key(name)}").text
        assert name not in page and "&lt;script&gt;" in page
        assert "&lt;qualitative &amp; raw&gt;" in page
        assert "Не указана" in page and "Не указан" in page
        assert "Число неподтверждённых строк может быть неполным" in page
        assert name not in client.get("/labs").text


@pytest.mark.parametrize("name", ["Маркер", " МАРКЕР. ", "маркер…", "маркер:\t"])
def test_name_key_is_safe_and_deterministic(name):
    assert analyte_key(name) == analyte_key("Маркер")
    assert normalized_name("A   B.") == "a b"
    assert analyte_key("Холестерин общий") != analyte_key("Общий холестерин")
    assert unit_key(" MG / L ") == unit_key("mg / l")
    assert unit_key(None) != unit_key("")
    assert unit_key("mg/l") != unit_key("mg/l.")


def test_list_previous_reference_and_report_groups_use_loaded_history(runtime):
    service, paths = runtime
    add(service, "older", unit="ммоль/л", date={"value": "2099-01-01", "precision": "date"})
    add(service, "latest", unit=None, printed={"value": "2099-02-01", "precision": "date"})
    add(service, "other-name", name="Другой маркер")
    listing = service.analytes()
    before = copy.deepcopy(listing)
    groups = analyte_groups(listing)
    assert listing == before
    item = next(item for group in groups for item in group["items"] if item["name"] == "Маркер")
    assert item["latest"]["row"]["reference_raw"] == "Референс latest"
    assert item["previous"]["row"]["unit_raw"] == "ммоль/л"
    assert item["previous"]["date"]["value"] == "2099-01-01"
    with client_for(paths) as client:
        page = client.get("/labs").text
        assert 'class="lab-table lab-analyte-table"' in page
        assert 'data-lab-count="2"' in page and 'data-lab-count="1"' in page
        assert 'aria-label="2 результата"' in page
        assert "Референс latest" in page and "ммоль/л · 1 янв 2099" in page
        assert 'class="lab-literal">не указана</td>' in page
        assert 'title="Пометка из отчёта лаборатории"' in page
        assert 'data-lab-filters hidden' in page


def test_history_scatter_keeps_unit_dates_boundaries_and_missing_rows_separate():
    def entry(value, day, *, unit="мг/л", kind="numeric", comparator=None):
        return {"row": {"decimal": value, "value_kind": kind, "comparator": comparator,
                        "unit_raw": unit},
                "date": {"value": day} if day else None, "sort_date": day or ""}

    rows = [entry("10", "2099-01-11", comparator="<"),
            entry(None, "2099-01-06", kind="qualitative"),
            entry("0", "2099-01-01"), entry("99", None)]
    history = {"groups": [{"unit": "мг/л", "rows": rows},
                          {"unit": "ммоль/л", "rows": [entry("500", "2099-02-01")]}]}
    before = copy.deepcopy(history)
    chart = history_chart(history)
    assert history == before
    assert chart["unit"] == "мг/л" and chart["omitted"] == 2
    assert len(chart["points"]) == 2
    zero, boundary = chart["points"]
    assert zero["entry"]["row"]["decimal"] == "0" and zero["y"] == 90
    assert zero["index"] == 2 and zero["x"] == 5
    assert boundary["boundary"] and boundary["index"] == 0 and boundary["x"] == 95
    assert chart["has_boundaries"]
    assert [tick["value"] for tick in chart["ticks"]] == [Decimal(0), Decimal(5), Decimal(10)]
    assert history_chart({"groups": [{"unit": None, "rows": rows[:1]}]}) is None
    assert history_chart(None) is None


@pytest.mark.parametrize("value", ["0", "-0.00001", "9" * 99, "0." + "0" * 96 + "1"])
def test_history_scatter_equal_values_and_same_day_are_finite(value):
    entry = {"row": {"value_kind": "numeric", "decimal": value, "comparator": None},
             "date": {"value": "2099-01-01"}, "sort_date": "2099-01-01"}
    chart = history_chart({"groups": [{"unit": None, "rows": [entry, copy.deepcopy(entry)]}]})
    assert len(chart["points"]) == 2
    assert all(point["x"] == 50 and 10 <= point["y"] <= 90 for point in chart["points"])
    assert 2 <= len(chart["ticks"]) <= 4
