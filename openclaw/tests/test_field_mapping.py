from core.config import load_settings


def test_chapter_task_required_fields_exist() -> None:
    fields = load_settings().field_mapping["章节任务表"]["fields"]
    required_fields = {
        "生产状态",
        "发布状态",
        "内容锁定状态",
        "运行锁定时间",
        "人工审核结果",
        "人工审核意见",
        "审核人",
        "审核时间",
        "流程重试次数",
        "内容返工次数",
        "AI建议审核等级",
        "人工审核优先级",
        "排班生成时间",
    }
    assert required_fields <= set(fields)


def test_guard_related_tables_have_source_core_and_confirmation_fields() -> None:
    mapping = load_settings().field_mapping
    required = {
        "人物档案表": "是否核心",
        "世界观设定表": "是否核心",
        "势力组织表": "是否核心",
        "伏笔追踪表": "是否主线伏笔",
        "长期记忆表": "是否核心",
    }
    for table_name, core_field in required.items():
        fields = mapping[table_name]["fields"]
        assert {"来源状态", core_field, "确认状态"} <= set(fields)


def test_all_fields_have_field_id_after_real_mapping_sync() -> None:
    mapping = load_settings().field_mapping
    missing = []
    for table_name, table in mapping.items():
        for field_name, field in table["fields"].items():
            if not field.get("field_id"):
                missing.append(f"{table_name}.{field_name}")
    assert not missing


def test_local_semantic_aliases_point_to_remote_field_names() -> None:
    fields = load_settings().field_mapping["章节任务表"]["fields"]
    assert fields["人工审核优先级"]["remote_field_name"] == "人工审核优先级排班"
    assert fields["排班生成时间"]["remote_field_name"] == "生成时间"
