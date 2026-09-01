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


def test_is_active_container() -> None:
    assert ct.is_active_container(
        {"status": "new", "available_actions": ["delete"]}
    )
    assert not ct.is_active_container({"status": "shipped", "available_actions": []})
    assert not ct.is_active_container({"status": "cancelled", "available_actions": []})


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
