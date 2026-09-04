"""Ozon FBS carriage containers — normalize / active filter / create validation."""

from __future__ import annotations

from review_processor import ozon_fbs_containers as ct


class _FakeClient:
    def __init__(self):
        self.created = []
        self.cancelled = []
        self.labels = []
        self.list_body = None

    def carriage_container_list(self, body):
        self.list_body = body
        return {
            "cursor": "",
            "containers": [
                {
                    "container_id": 111,
                    "container_number": 1,
                    "status": "new",
                    "cargo_type": "pallet",
                    "sort_type": "sort",
                    "count_of_postings": 3,
                    "available_actions": ["approve", "delete", "get_label_container"],
                    "warehouse_id": 5,
                    "warehouse_name": "WH",
                },
                {
                    "container_id": 222,
                    "container_number": 2,
                    "status": "shipped",
                    "cargo_type": "pallet",
                    "sort_type": "non-sort",
                    "count_of_postings": 1,
                    "available_actions": [],
                    "warehouse_id": 5,
                },
                {
                    "container_id": 444,
                    "container_number": 4,
                    "status": "acceptance_in_progress",
                    "cargo_type": "pallet",
                    "sort_type": "sort",
                    "count_of_postings": 2,
                    "available_actions": [],
                    "warehouse_id": 5,
                    "created_at": "2026-09-01T10:00:00Z",
                },
                {
                    "container_id": 555,
                    "container_number": 5,
                    "status": "finished",
                    "cargo_type": "pallet",
                    "sort_type": "sort",
                    "count_of_postings": 4,
                    "available_actions": [],
                    "warehouse_id": 5,
                    "created_at": "2026-09-01T12:00:00Z",
                },
                {
                    "container_id": 333,
                    "container_number": 3,
                    "status": "new",
                    "cargo_type": "pallet",
                    "sort_type": "sort",
                    "count_of_postings": 0,
                    "available_actions": ["delete", "get_label_container"],
                    "warehouse_id": 99,  # other warehouse
                },
            ],
        }

    def carriage_container_create(self, **kwargs):
        self.created.append(kwargs)
        return {"container_ids": [501, 502]}

    def carriage_container_cancel(self, *, container_ids):
        self.cancelled.append(list(container_ids))
        return {"task_id": 1, "error_containers": []}

    def carriage_container_label_get(self, *, container_ids):
        self.labels.append(list(container_ids))
        return {
            "content": {
                "content_type": "application/pdf",
                "file_content": "JVBERi0x",
            },
            "error_containers": [],
        }


def test_list_containers_filters_shipped_and_other_warehouse() -> None:
    client = _FakeClient()
    out = ct.list_containers(client, warehouse_id=5)
    assert out["ok"] is True
    ids = [x["container_id"] for x in out["items"]]
    assert ids == [111]
    assert out["items"][0]["order_count"] == 3
    assert out["items"][0]["status_label"] == "Новое"
    assert client.list_body["filter"]["warehouse_id"] == 5


def test_list_containers_include_sc_accepted() -> None:
    client = _FakeClient()
    hidden = ct.list_containers(client, warehouse_id=5)
    assert [x["container_id"] for x in hidden["items"]] == [111]

    shown = ct.list_containers(client, warehouse_id=5, include_sc_accepted=True)
    ids = [x["container_id"] for x in shown["items"]]
    # Newest created_at first among SC-accepted + active rows.
    assert ids == [555, 444, 111]
    sc_row = next(x for x in shown["items"] if x["container_id"] == 444)
    assert sc_row["status_label"] == "Принято на СЦ"
    assert sc_row["can_fill"] is False
    finished = next(x for x in shown["items"] if x["container_id"] == 555)
    assert finished["status_label"] == "Завершено на СЦ"
    assert finished["can_fill"] is False


def test_list_containers_sorts_newest_created_first() -> None:
    class _Client(_FakeClient):
        def carriage_container_list(self, body):
            self.list_body = body
            return {
                "cursor": "",
                "containers": [
                    {
                        "container_id": 10,
                        "container_number": 10,
                        "status": "new",
                        "cargo_type": "pallet",
                        "sort_type": "sort",
                        "count_of_postings": 0,
                        "available_actions": ["delete"],
                        "warehouse_id": 5,
                        "created_at": "2026-09-01T08:00:00Z",
                    },
                    {
                        "container_id": 20,
                        "container_number": 1,
                        "status": "new",
                        "cargo_type": "pallet",
                        "sort_type": "sort",
                        "count_of_postings": 0,
                        "available_actions": ["delete"],
                        "warehouse_id": 5,
                        "created_at": "2026-09-02T18:00:00Z",
                    },
                    {
                        "container_id": 30,
                        "container_number": 30,
                        "status": "new",
                        "cargo_type": "pallet",
                        "sort_type": "sort",
                        "count_of_postings": 0,
                        "available_actions": ["delete"],
                        "warehouse_id": 5,
                        "created_at": "2026-09-02T09:00:00Z",
                    },
                ],
            }

    out = ct.list_containers(_Client(), warehouse_id=5)
    assert [x["container_id"] for x in out["items"]] == [20, 30, 10]


def test_list_containers_sorts_by_utc_not_lexicographic_offset() -> None:
    """Same absolute time with different TZ offsets must not invert order."""

    class _Client(_FakeClient):
        def carriage_container_list(self, body):
            self.list_body = body
            return {
                "cursor": "",
                "containers": [
                    {
                        "container_id": 1,
                        "container_number": 1,
                        "status": "new",
                        "cargo_type": "pallet",
                        "sort_type": "sort",
                        "count_of_postings": 0,
                        "available_actions": ["delete"],
                        "warehouse_id": 5,
                        # 12:00+03:00 == 09:00Z — older than the Z row below.
                        "created_at": "2026-09-02T12:00:00+03:00",
                    },
                    {
                        "container_id": 2,
                        "container_number": 2,
                        "status": "new",
                        "cargo_type": "pallet",
                        "sort_type": "sort",
                        "count_of_postings": 0,
                        "available_actions": ["delete"],
                        "warehouse_id": 5,
                        "created_at": "2026-09-02T10:00:00Z",
                    },
                    {
                        "container_id": 3,
                        "container_number": 3,
                        "status": "new",
                        "cargo_type": "pallet",
                        "sort_type": "sort",
                        "count_of_postings": 0,
                        "available_actions": ["delete"],
                        "warehouse_id": 5,
                        "created_at": "",
                    },
                ],
            }

    out = ct.list_containers(_Client(), warehouse_id=5)
    # Lexicographic string sort would put +03:00 before Z incorrectly.
    assert [x["container_id"] for x in out["items"]] == [2, 1, 3]


def test_is_active_container() -> None:
    assert ct.is_active_container(
        {"status": "new", "available_actions": ["delete"]}
    )
    assert not ct.is_active_container({"status": "shipped", "available_actions": []})
    assert not ct.is_active_container({"status": "cancelled", "available_actions": []})
    assert not ct.is_active_container(
        {"status": "acceptance_in_progress", "available_actions": []}
    )
    assert not ct.is_active_container({"status": "finished", "available_actions": []})
    assert ct.is_sc_accepted_container({"status": "acceptance_in_progress"})
    assert ct.is_sc_accepted_container({"status": "finished"})
    assert ct.status_label("acceptance_in_progress") == "Принято на СЦ"
    assert ct.status_label("finished") == "Завершено на СЦ"


def test_create_containers_validation() -> None:
    client = _FakeClient()
    out = ct.create_containers(
        client,
        warehouse_id=5,
        containers_count=2,
        sort_type="non-sort",
        cargo_type="pallet",
    )
    assert out["created"] == 2
    assert client.created[0]["sort_type"] == "non-sort"
    try:
        ct.create_containers(client, warehouse_id=5, containers_count=0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_delete_and_labels() -> None:
    client = _FakeClient()
    deleted = ct.delete_containers(client, container_ids=[111])
    assert deleted["deleted"] == 1
    labels = ct.get_container_labels_pdf(client, container_ids=[111])
    assert labels["file_content"] == "JVBERi0x"


def test_can_print_not_always_true() -> None:
    row = ct._normalize_container(
        {
            "container_id": 9,
            "container_number": 1,
            "status": "shipped",
            "available_actions": [],
            "count_of_postings": 0,
        }
    )
    assert row is not None
    assert row["can_print"] is False
    row2 = ct._normalize_container(
        {
            "container_id": 10,
            "container_number": 2,
            "status": "new",
            "available_actions": ["delete", "get_label_container"],
            "count_of_postings": 0,
        }
    )
    assert row2 is not None
    assert row2["can_print"] is True


def test_friendly_ozon_error() -> None:
    msg = ct._friendly_ozon_error(
        RuntimeError('Ozon HTTP 400: {"code":3,"message":"FORBIDDEN_TO_CREATE_SORT_BOX"}')
    )
    assert msg == "FORBIDDEN_TO_CREATE_SORT_BOX"


def test_container_accepts_fill_and_can_approve() -> None:
    open_row = ct._normalize_container(
        {
            "container_id": 1,
            "container_number": 1,
            "status": "new",
            "available_actions": ["approve", "delete", "get_label_container"],
            "count_of_postings": 2,
        }
    )
    assert open_row is not None
    assert open_row["can_approve"] is True
    assert open_row["can_fill"] is True
    assert ct.container_accepts_fill(open_row) is True

    locked = ct._normalize_container(
        {
            "container_id": 2,
            "container_number": 2,
            "status": "approved",
            "available_actions": ["get_label_container"],
            "count_of_postings": 2,
        }
    )
    assert locked is not None
    assert locked["can_approve"] is False
    assert locked["can_fill"] is False
    assert locked["can_print"] is True
    assert ct.container_accepts_fill(locked) is False
    assert ct.is_active_container(locked) is True


def test_approve_containers_success_and_errors() -> None:
    class _ApproveClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.approved = []
            self.tasks = []
            self.approve_resp = {"task_id": 42, "error_containers": []}
            self.task_resp = {"status": "completed", "error_message": ""}

        def carriage_container_approve(self, *, container_ids):
            self.approved.append(list(container_ids))
            return dict(self.approve_resp)

        def carriage_container_task_info(self, *, task_id):
            self.tasks.append(int(task_id))
            return dict(self.task_resp)

    client = _ApproveClient()
    out = ct.approve_containers(client, container_ids=[111])
    assert out["ok"] is True
    assert out["approved"] == 1
    assert client.approved == [[111]]
    assert client.tasks == [42]
    assert "Подтверждено" in out["message"]

    client.approve_resp = {
        "task_id": 0,
        "error_containers": [{"container_id": 111, "error_message": "CONTAINER_EMPTY"}],
    }
    out_err = ct.approve_containers(client, container_ids=[111])
    assert out_err["ok"] is False
    assert out_err["approved"] == 0
    assert out_err["errors"][0]["error"] == "CONTAINER_EMPTY"

    client.approve_resp = {"task_id": 7, "error_containers": []}
    client.task_resp = {"status": "failed", "error_message": "APPROVE_FAILED"}
    out_fail = ct.approve_containers(client, container_ids=[111])
    assert out_fail["ok"] is False
    assert any("APPROVE_FAILED" in (e.get("error") or "") for e in out_fail["errors"])


def test_build_approve_precheck_flags_sync_errors_and_unbound() -> None:
    from unittest.mock import MagicMock, patch

    repo = MagicMock()
    with patch.object(
        ct.oz_sup,
        "list_active_supply_posting_numbers",
        return_value=["A-1", "B-1", "C-1", "D-1"],
    ), patch.object(
        ct,
        "load_container_bind_map",
        return_value={
            "A-1": {"container_id": 10, "container_sync_error": "FILL_FAILED"},
            "B-1": {"container_id": 10, "container_sync_error": ""},
            "C-1": {"container_id": 20, "container_sync_error": ""},
            "D-1": {"container_id": None, "container_sync_error": ""},
        },
    ):
        out = ct.build_approve_precheck(
            repo, user_id=1, source_id=2, supply_id="S1", container_id=10
        )
    assert out["ok"] is True
    assert out["total_orders"] == 4
    assert out["bound_to_container"] == 2
    assert out["bound_other"] == 1
    assert out["unbound"] == 1
    assert out["has_unbound"] is True
    assert out["has_sync_errors"] is True
    assert out["requires_force"] is True
    assert out["sync_error_count"] == 1
    assert out["sync_errors"][0]["posting_number"] == "A-1"

    with patch.object(
        ct.oz_sup,
        "list_active_supply_posting_numbers",
        return_value=["A-1", "B-1"],
    ), patch.object(
        ct,
        "load_container_bind_map",
        return_value={
            "A-1": {"container_id": 10, "container_sync_error": ""},
            "B-1": {"container_id": 10, "container_sync_error": ""},
        },
    ):
        clean = ct.build_approve_precheck(
            repo, user_id=1, source_id=2, supply_id="S1", container_id=10
        )
    assert clean["requires_force"] is False
    assert clean["has_sync_errors"] is False
    assert clean["has_unbound"] is False
    assert clean["bound_to_container"] == 2


def test_build_approve_precheck_excludes_cancelled_via_active_list() -> None:
    """Refusals left in posting_numbers_json must not inflate supply totals."""
    from unittest.mock import MagicMock, patch

    repo = MagicMock()
    with patch.object(
        ct.oz_sup,
        "list_active_supply_posting_numbers",
        return_value=["A-1", "B-1", "C-1"],
    ) as active_list, patch.object(
        ct,
        "load_container_bind_map",
        return_value={
            "A-1": {"container_id": 10, "container_sync_error": ""},
            "B-1": {"container_id": 10, "container_sync_error": ""},
            "C-1": {"container_id": 10, "container_sync_error": ""},
        },
    ):
        out = ct.build_approve_precheck(
            repo,
            user_id=1,
            source_id=2,
            supply_id="S1",
            container_id=10,
            posting_tab="awaiting_deliver",
        )
    active_list.assert_called_once_with(
        repo,
        user_id=1,
        source_id=2,
        supply_id="S1",
        posting_tab="awaiting_deliver",
    )
    assert out["total_orders"] == 3
    assert out["bound_to_container"] == 3
    assert out["unbound"] == 0
    assert out["has_unbound"] is False


def test_enrich_containers_rewrites_order_count_from_local_active() -> None:
    from unittest.mock import MagicMock, patch

    repo = MagicMock()
    listed = {
        "ok": True,
        "items": [
            {"container_id": 10, "order_count": 100},
            {"container_id": 20, "order_count": 40},
            {"container_id": 30, "order_count": 5},
        ],
    }
    with patch.object(
        ct, "get_supply_moved_to_delivering_at", return_value=""
    ), patch.object(
        ct,
        "_active_local_order_counts_by_container",
        return_value={10: 80, 20: 36},
    ), patch.object(
        ct.oz_sup,
        "list_active_supply_posting_numbers",
        return_value=["x"] * 116,
    ):
        out = ct.enrich_containers_for_supply_modal(
            repo, user_id=1, source_id=2, supply_id="S1", listed=listed
        )
    by_id = {int(x["container_id"]): x for x in out["items"]}
    assert by_id[10]["order_count"] == 80
    assert by_id[10]["order_count_ozon"] == 100
    assert by_id[20]["order_count"] == 36
    # No local binds for 30 → keep Ozon count (warehouse list is shared).
    assert by_id[30]["order_count"] == 5
    assert by_id[30]["order_count_ozon"] == 5
    assert out["active_order_count"] == 116


