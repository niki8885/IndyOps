from app.services.blueprint_collection import parse_blueprint_list


def test_groups_repeated_lines():
    text = """
Miner II Blueprint
Acolyte II Blueprint
Acolyte II Blueprint
Acolyte II Blueprint
Armor Command Burst II Blueprint
Armor Command Burst II Blueprint
"""
    out = parse_blueprint_list(text)
    assert out == [
        {"name": "Miner II Blueprint", "count": 1},
        {"name": "Acolyte II Blueprint", "count": 3},
        {"name": "Armor Command Burst II Blueprint", "count": 2},
    ]


def test_preserves_first_seen_order():
    out = parse_blueprint_list("B\nA\nB\nA\nA")
    assert [g["name"] for g in out] == ["B", "A"]
    assert {g["name"]: g["count"] for g in out} == {"B": 2, "A": 3}


def test_explicit_x_suffix_and_tab_quantity():
    assert parse_blueprint_list("Miner II Blueprint x20")[0] == {"name": "Miner II Blueprint", "count": 20}
    assert parse_blueprint_list("Hammerhead II Blueprint\t15\tMedium Drone")[0] == \
        {"name": "Hammerhead II Blueprint", "count": 15}
    # suffix + repeats add up
    out = parse_blueprint_list("Warden II Blueprint x5\nWarden II Blueprint")
    assert out == [{"name": "Warden II Blueprint", "count": 6}]


def test_blank_and_whitespace_lines_ignored():
    assert parse_blueprint_list("\n   \n\tFoo Blueprint\t1\n") == [{"name": "Foo Blueprint", "count": 1}]
    assert parse_blueprint_list("") == []
