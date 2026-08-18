from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Iterable

from device_gateway.fanqie_inspiration_workflow import InspirationSnapshot
from device_gateway.ui_coordinates import normalize_semantic_text

GENRE_KEYWORDS = {
    "玄幻": ("玄幻", "修仙", "仙侠", "灵气", "宗门", "异能"),
    "都市": ("都市", "神豪", "职场", "校园", "医生", "鉴宝"),
    "游戏": ("游戏", "网游", "玩家", "副本", "职业", "转职"),
    "科幻": ("科幻", "星际", "机甲", "末日", "废土", "赛博"),
    "悬疑": ("悬疑", "诡异", "规则", "推理", "怪谈"),
    "女频": ("女频", "重生", "穿越", "宫斗", "甜宠", "婚恋"),
}
HOT_ELEMENTS = (
    "系统",
    "重生",
    "穿越",
    "末世",
    "灵气复苏",
    "全民",
    "觉醒",
    "转职",
    "副本",
    "规则怪谈",
    "直播",
    "种田",
    "神豪",
    "反派",
    "御兽",
    "囤货",
    "签到",
    "天灾",
    "唯一玩家",
    "隐藏职业",
    "高武",
    "游戏",
    "单女主",
    "搞笑",
    "异能",
    "同人",
    "诡异",
    "无限",
    "扮演",
    "修仙",
    "无敌",
    "年代",
    "谍战",
    "科技",
    "进化",
    "武侠",
    "西游",
)
STOPWORDS = {"开书灵感", "常用工具", "查看更多", "我的", "作品", "消息", "活动", "数据", "推荐素材"}


@dataclass(frozen=True)
class TopicCandidate:
    topic_id: str
    genre: str
    keywords: list[str]
    core_selling_point: str
    target_reader: str
    source: str
    source_terms: list[str]
    rank_heat_score: int
    search_heat_score: int
    trend_score: int
    competition_score: int
    differentiation_score: int
    long_serial_score: int
    compliance_score: int
    total_score: int
    status: str = "待市场验证"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class TopicAnalyzer:
    def analyze_snapshot(self, snapshot: InspirationSnapshot, *, limit: int = 20) -> list[TopicCandidate]:
        text = "\n".join(page.text for page in snapshot.pages)
        return self.analyze_text(text, source="番茄开书灵感", limit=limit)

    def analyze_text(self, text: str, *, source: str = "番茄开书灵感", limit: int = 20) -> list[TopicCandidate]:
        terms = self._extract_terms(normalize_semantic_text(text))
        if not terms:
            return []
        term_counts = Counter(terms)
        element_counts = Counter(term for term in terms if term in HOT_ELEMENTS)
        genre_counts = Counter(self._infer_genres(terms))
        seeds = [term for term, _ in term_counts.most_common(limit * 2)]
        candidates = [
            self._build_candidate(index, self._best_genre(seed, genre_counts), self._related_keywords(seed, term_counts), source, term_counts)
            for index, seed in enumerate(seeds[: limit * 2], start=1)
        ]
        unique: dict[str, TopicCandidate] = {}
        for candidate in candidates:
            current = unique.get(candidate.topic_id)
            if current is None or candidate.total_score > current.total_score:
                unique[candidate.topic_id] = candidate
        return sorted(unique.values(), key=lambda item: item.total_score, reverse=True)[:limit]

    def _build_candidate(
        self,
        index: int,
        genre: str,
        keywords: list[str],
        source: str,
        term_counts: Counter[str],
    ) -> TopicCandidate:
        del index
        heat = min(100, 45 + sum(term_counts.get(term, 0) * 8 for term in keywords))
        search_heat = min(100, 35 + len(keywords) * 9 + max(term_counts.get(term, 0) for term in keywords))
        competition = min(95, 35 + sum(1 for term in keywords if term in HOT_ELEMENTS) * 10)
        differentiation = max(45, 92 - competition // 2 + len(set(keywords)) * 4)
        long_serial = min(96, 65 + (12 if genre in {"玄幻", "游戏", "科幻"} else 6) + len(keywords) * 3)
        compliance = 76 if genre == "悬疑" else 88
        trend = min(95, (heat + search_heat) // 2)
        total = round(
            heat * 0.30
            + search_heat * 0.25
            + trend * 0.15
            + differentiation * 0.15
            + long_serial * 0.10
            + compliance * 0.05
            - competition * 0.10
        )
        topic_id = "TOPIC-" + hashlib.sha1((genre + "|" + "|".join(keywords)).encode()).hexdigest()[:10].upper()
        return TopicCandidate(
            topic_id=topic_id,
            genre=genre,
            keywords=keywords,
            core_selling_point=self._selling_point(genre, keywords),
            target_reader="女频" if genre == "女频" else "男频",
            source=source,
            source_terms=keywords,
            rank_heat_score=heat,
            search_heat_score=search_heat,
            trend_score=trend,
            competition_score=competition,
            differentiation_score=differentiation,
            long_serial_score=long_serial,
            compliance_score=compliance,
            total_score=max(0, min(100, total)),
        )

    def _extract_terms(self, text: str) -> list[str]:
        terms: list[str] = []
        for element in HOT_ELEMENTS:
            if element in text:
                terms.extend([element] * max(1, text.count(element)))
        known_genre_terms = {word for words in GENRE_KEYWORDS.values() for word in words}
        for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}", text):
            if token in STOPWORDS or token.isdigit():
                continue
            if token in HOT_ELEMENTS or token in known_genre_terms:
                terms.append(token)
        return terms

    def _infer_genres(self, terms: Iterable[str]) -> list[str]:
        genres = []
        for term in terms:
            for genre, keywords in GENRE_KEYWORDS.items():
                if any(keyword in term or term in keyword for keyword in keywords):
                    genres.append(genre)
        return genres

    def _best_genre(self, seed: str, genre_counts: Counter[str]) -> str:
        for genre, keywords in GENRE_KEYWORDS.items():
            if any(keyword in seed or seed in keyword for keyword in keywords):
                return genre
        return genre_counts.most_common(1)[0][0] if genre_counts else "都市"

    def _related_keywords(self, seed: str, term_counts: Counter[str]) -> list[str]:
        ranked = [term for term, _ in term_counts.most_common() if term == seed or term in HOT_ELEMENTS]
        result = ranked[:5] or [seed]
        if seed not in result:
            result.insert(0, seed)
        return result[:5]

    def _selling_point(self, genre: str, keywords: list[str]) -> str:
        joined = " + ".join(keywords[:4])
        if genre == "游戏":
            return f"主角围绕{joined}展开成长，在副本与职业体系中抢占先机，形成持续升级爽点。"
        if genre == "玄幻":
            return f"主角借助{joined}突破底层限制，在势力碰撞中逐步揭开世界核心秘密。"
        if genre == "科幻":
            return f"主角在{joined}驱动的危机中寻找生存路径，用技术与信息差完成逆转。"
        return f"围绕{joined}设计强钩子开局，用明确目标、持续冲突和阶段反转支撑长线连载。"
