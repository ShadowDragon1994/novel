from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.feishu_client import FeishuClient


@dataclass(frozen=True)
class AcceptanceChapter:
    chapter_id: str
    title: str
    card: str


ACCEPTANCE_CHAPTERS = (
    AcceptanceChapter(
        "NOVEL-01-CH-004",
        "第四章：灵监会的条件",
        "林舟从理智变异体口中得知污染源并非意外，灵监会提出以父亲旧案交换合作。"
        "主角一面周旋，一面用新觉醒的灵脉感知锁定地下泄漏通道，结尾发现父亲留下的秘密标记。",
    ),
    AcceptanceChapter(
        "NOVEL-01-CH-005",
        "第五章：父亲的编号",
        "林舟追查秘密标记，在灵监会封存档案中找到父亲的实验编号。调查过程中遭遇污染体围攻，"
        "他首次主动运转灵脉救下同伴，并发现自身能力会吸收污染。",
    ),
    AcceptanceChapter(
        "NOVEL-01-CH-006",
        "第六章：午夜封锁线",
        "东郊污染突然扩散，城市午夜封锁。林舟必须在灵监会全面清场前进入第二节点，"
        "阻止污染沿地下管网蔓延，结尾出现与父亲声音相同的神秘通讯。",
    ),
    AcceptanceChapter(
        "NOVEL-02-CH-003",
        "第三章：公会来客",
        "苏晨获得关键道具后，神秘公会派人登门试探。主角利用前世经验识破交易陷阱，"
        "并从对方口中套出三年后灵气枯竭计划的第一条线索。",
    ),
    AcceptanceChapter(
        "NOVEL-02-CH-004",
        "第四章：旧校灵井",
        "苏晨赶往母校废弃实验楼寻找前世宗门的第一口灵井，却发现公会已提前布置封锁。"
        "他带领一名可信同学潜入，在井底找到残缺阵盘。",
    ),
    AcceptanceChapter(
        "NOVEL-02-CH-005",
        "第五章：阵盘重启",
        "苏晨尝试修复残缺阵盘，灵井异动引来多方争夺。他以有限修为重启护山阵雏形，"
        "正式收下第一名弟子，同时暴露重生者不应掌握的秘法。",
    ),
    AcceptanceChapter(
        "NOVEL-03-CH-003",
        "第三章：变异种子",
        "陈默在营地特殊作物中发现会随异能点进化的变异种子。为了获得水源，"
        "他带队探索废弃商场，并与一群控制物资的幸存者发生冲突。",
    ),
    AcceptanceChapter(
        "NOVEL-03-CH-004",
        "第四章：地铁回声",
        "营地夜间传来地铁隧道的求救广播。陈默带人返回最初遇袭地点，发现双头犬只是低阶猎食者，"
        "地下深处有能够模仿人声的生物。",
    ),
    AcceptanceChapter(
        "NOVEL-03-CH-005",
        "第五章：第一块农田",
        "陈默将变异种子种入净化后的土地，建立末世第一块稳定农田。"
        "收获前夕怪物潮逼近，幸存者内部也出现偷窃种子的叛徒。",
    ),
    AcceptanceChapter(
        "NOVEL-04-CH-005",
        "第五章：被删去的名字",
        "方宇读取记忆样本，发现守夜人计划名单中自己的名字被人为删除。"
        "陈叔在监控中留下限时指引，要求他在净化塔重启前找到S-017。",
    ),
    AcceptanceChapter(
        "NOVEL-04-CH-006",
        "第六章：S-017醒来",
        "方宇打开封存舱，S-017苏醒并认出他掌心的蓝色纹路。实验室安保全面启动，"
        "两人必须穿过污染隔离区逃离，途中揭示守夜人计划曾分裂成两派。",
    ),
    AcceptanceChapter(
        "NOVEL-04-CH-007",
        "第七章：净化塔倒计时",
        "净化塔进入异常倒计时，城内守夜人被下令追捕方宇。他决定不再逃亡，"
        "利用记忆样本公开部分真相，并潜入塔基寻找控制核心。",
    ),
    AcceptanceChapter(
        "NOVEL-05-CH-003",
        "第三章：传承第一课",
        "戒中残魂传授张扬第一部修炼功法，却要求他在天亮前完成引气入体。"
        "主角利用现代物品改良修炼环境，同时发现残魂隐瞒了门派覆灭的细节。",
    ),
    AcceptanceChapter(
        "NOVEL-05-CH-004",
        "第四章：古玩街追踪者",
        "张扬再次前往古玩街寻找传承线索，被神秘修士跟踪。"
        "他借戒指中的阵法知识反制对方，夺得一块刻有同门印记的残碑。",
    ),
    AcceptanceChapter(
        "NOVEL-05-CH-005",
        "第五章：残碑血字",
        "残碑遇到张扬的灵力后浮现血字，指出门派中仍有叛徒存活。"
        "戒中残魂情绪失控，主角必须判断师父是否可信，结尾收到来自同一传承的隔空传讯。",
    ),
)

PUBLISHED_CHAPTER_IDS = {
    "NOVEL-01-CH-004",
    "NOVEL-02-CH-003",
    "NOVEL-03-CH-003",
    "NOVEL-04-CH-005",
    "NOVEL-05-CH-003",
}

DEVICE_BY_NOVEL = {
    "NOVEL-01": "127.0.0.1:54511",
    "NOVEL-02": "127.0.0.1:54510",
    "NOVEL-03": "127.0.0.1:54512",
    "NOVEL-04": "127.0.0.1:54513",
    "NOVEL-05": "127.0.0.1:54518",
}


def build_chapter_update(
    item: AcceptanceChapter,
    *,
    regenerate_published: bool = False,
) -> dict[str, Any]:
    update: dict[str, Any] = {"章节名": item.title, "章节卡内容": item.card}
    if item.chapter_id not in PUBLISHED_CHAPTER_IDS or regenerate_published:
        update.update(
            {
                "生产状态": "待创作/Pending",
                "内容锁定状态": "否/No",
                "流程重试次数": 0,
                "内容返工次数": 0,
                "错误信息": "",
                "计划发布时间": None,
                "实际发布时间": None,
                "人工审核结果": None,
            }
        )
        if item.chapter_id not in PUBLISHED_CHAPTER_IDS:
            update["发布状态"] = "未排期/Unscheduled"
    return update


def build_approval_update(reviewed_at: datetime) -> dict[str, Any]:
    return {
        "人工审核结果": "通过",
        "生产状态": "已定稿/Finalized",
        "内容锁定状态": "是/Yes",
        "审核时间": int(reviewed_at.timestamp() * 1000),
        "错误信息": "",
    }


def _by_field(records: list[dict[str, Any]], field_name: str) -> dict[str, dict[str, Any]]:
    return {
        str(record.get("fields", record).get(field_name)): record
        for record in records
        if record.get("fields", record).get(field_name)
    }


async def repair(
    *,
    apply: bool,
    regenerate_published: bool = False,
    devices_only: bool = False,
    approve: bool = False,
) -> dict[str, int]:
    load_dotenv(PROJECT_ROOT / "config" / ".env")
    async with FeishuClient() as client:
        chapters = _by_field(await client.list_records("章节任务表"), "章节ID")
        account_records = await client.list_records("账号管理表")
        accounts = _by_field(account_records, "绑定小说ID")
        accounts.update(
            {
                key: value
                for key, value in _by_field(account_records, "小说ID").items()
                if key not in accounts
            }
        )
        versions = await client.list_records("正文版本表")

        missing = [item.chapter_id for item in ACCEPTANCE_CHAPTERS if item.chapter_id not in chapters]
        if missing:
            raise RuntimeError(f"章节任务不存在，停止修复: {', '.join(missing)}")

        counters = {"chapters": 0, "versions_archived": 0, "accounts": 0}
        for item in () if devices_only else ACCEPTANCE_CHAPTERS:
            if regenerate_published and item.chapter_id not in PUBLISHED_CHAPTER_IDS:
                continue
            record = chapters[item.chapter_id]
            update = (
                build_approval_update(datetime.now())
                if approve
                else build_chapter_update(item, regenerate_published=regenerate_published)
            )
            current = record.get("fields", record)
            update = {key: value for key, value in update.items() if current.get(key) != value}
            if not update:
                continue
            print(json.dumps({"chapter_id": item.chapter_id, "update": update}, ensure_ascii=False))
            if apply:
                await client.update_record("章节任务表", record["record_id"], update)
            counters["chapters"] += 1

        archive_chapter_ids = (
            PUBLISHED_CHAPTER_IDS
            if regenerate_published
            else {item.chapter_id for item in ACCEPTANCE_CHAPTERS} - PUBLISHED_CHAPTER_IDS
        )
        for version in () if devices_only or approve else versions:
            fields = version.get("fields", version)
            if fields.get("章节ID") not in archive_chapter_ids:
                continue
            update = {"版本类型": "废弃稿/Discarded", "是否当前最终版": False}
            update = {key: value for key, value in update.items() if fields.get(key) != value}
            if not update:
                continue
            print(
                json.dumps(
                    {"version_record_id": version["record_id"], "chapter_id": fields.get("章节ID"), "update": update},
                    ensure_ascii=False,
                )
            )
            if apply:
                await client.update_record("正文版本表", version["record_id"], update)
            counters["versions_archived"] += 1

        for novel_id, device_id in (() if approve else DEVICE_BY_NOVEL.items()):
            account_record = accounts.get(novel_id)
            if not account_record:
                raise RuntimeError(f"小说未绑定账号，停止修复: {novel_id}")
            update = {"红手指设备ID": device_id}
            current = account_record.get("fields", account_record)
            update = {key: value for key, value in update.items() if current.get(key) != value}
            if not update:
                continue
            print(json.dumps({"novel_id": novel_id, "update": update}, ensure_ascii=False))
            if apply:
                await client.update_record("账号管理表", account_record["record_id"], update)
            counters["accounts"] += 1
        return counters


async def report_status() -> list[dict[str, Any]]:
    load_dotenv(PROJECT_ROOT / "config" / ".env")
    wanted = {item.chapter_id for item in ACCEPTANCE_CHAPTERS}
    async with FeishuClient() as client:
        records = await client.list_records("章节任务表")
    result = []
    for record in records:
        fields = record.get("fields", record)
        if fields.get("章节ID") not in wanted:
            continue
        result.append(
            {
                "章节ID": fields.get("章节ID"),
                "章节名": fields.get("章节名"),
                "生产状态": fields.get("生产状态"),
                "发布状态": fields.get("发布状态"),
                "最终字数": fields.get("最终字数"),
                "错误信息": fields.get("错误信息"),
            }
        )
    return sorted(result, key=lambda item: str(item["章节ID"]))


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="修复 2026-07-28 验收批次的乱码章节元数据")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只输出变更计划")
    parser.add_argument("--status", action="store_true", help="只输出本批次当前状态")
    parser.add_argument(
        "--regenerate-published",
        action="store_true",
        help="同时归档已发布 5 章的旧正文并重置生产状态，但保留发布状态",
    )
    parser.add_argument("--devices-only", action="store_true", help="只同步账号设备端口")
    parser.add_argument("--approve", action="store_true", help="将本批次 15 章标记为人工审核通过")
    args = parser.parse_args()
    if args.status:
        for item in await report_status():
            print(json.dumps(item, ensure_ascii=False))
        return 0
    counters = await repair(
        apply=args.apply,
        regenerate_published=args.regenerate_published,
        devices_only=args.devices_only,
        approve=args.approve,
    )
    print(json.dumps({"applied": args.apply, **counters}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
