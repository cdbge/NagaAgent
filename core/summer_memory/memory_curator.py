#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记忆审查（curation）：决定哪些五元组值得写进知识图谱。

背景
----
抽取器只被告知"提取所有可以识别出的五元组"，于是把**对话过程本身**也收了进去。
对现有 256 条数据的实测：

    - 203/256 条含 <=3 字的碎片主体或客体（"用户 --答--> 这个"）
    - 67 条主体是代词/指示词（"你"、"我"、"那些"）
    - 25 条在谈论对话/图谱自身（"记忆 --收录--> 对话内容"）
    - 同一实体多种拼写（"娜杰日达"/"娜杰达"/"娜日达"）

治理分两层：
    1. **提示词**（治本）：明确只记长期事实、代词必须消解。见 quintuple_extractor.py
    2. **本模块**（安全网）：写入前做确定性审查，拒掉碎片、归一化实体。
       纯规则、零额外模型调用，因此可以放在每次写入的必经路径上。

另外提供 ``curate_batch`` 用于**清理存量数据**并输出可读报告。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# 五元组：(主体, 主体类型, 关系, 客体, 客体类型)
Quintuple = Tuple[str, str, str, str, str]

# ---------------------------------------------------------------- 规则配置

# 用户与助手的规范名（可被调用方覆盖）
DEFAULT_USER_NAME = "用户"
DEFAULT_AI_NAME = "娜杰日达"

# 指向"用户"的说法
_USER_ALIASES = {
    "你", "您", "我", "咱", "咱们", "自己", "本人", "用户", "user", "User",
    "对方", "提问者", "主人",
}

# 指向"助手"的常见拼写变体（实测数据里出现过三种）
_AI_ALIASES = {
    "娜杰日达", "娜杰达", "娜日达", "娜迦", "娜加", "naga", "Naga", "NagaAgent",
    "助手", "AI", "ai", "你（助手）",
}

# 纯代词 / 指示词 / 泛称：不能作为实体
_PRONOUNS = {
    "你", "您", "我", "他", "她", "它", "咱", "咱们", "自己", "本人", "别人", "大家",
    "这个", "那个", "这些", "那些", "这", "那", "此", "该",
    "谁", "什么", "哪个", "哪些", "怎么", "为什么",
    "东西", "事情", "事", "内容", "部分", "方面", "情况", "问题", "一会儿", "一下",
    "一样", "一起", "时候", "地方", "方式", "一条", "两条", "三条",
    # 时间/处所泛称：不是稳定事实
    "下午", "上午", "晚上", "早上", "中午", "今天", "明天", "昨天", "今天下午",
    "这一下午", "这儿", "那儿", "这里", "那里", "一声", "起来", "那边", "这边",
    "三条线", "这种活", "一件事",
}

# 单字垃圾（语气词/量词/虚词）。注意「猫」「狗」「书」这类单字实体是合法的，
# 所以只列黑名单，不靠长度一刀切 —— 早先用 len>=2 会误杀「用户--养-->猫」。
_JUNK_SINGLE = {
    "性", "话", "爽", "的", "了", "是", "在", "和", "与", "或", "啊", "吧", "呢",
    "吗", "嘛", "呀", "哦", "嗯", "哈", "着", "过", "就", "都", "也", "还",
}

# 只作为「主体」出现的元话题：图谱/记忆自身不该成为知识的主体
# （注意「知识图谱」是用户的真实研究方向，可以作客体，故不在此列）
_META_HEADS = {
    "记忆", "记忆系统", "云图", "心智云图", "抽取器", "技能清单",
    "对话", "对话流水", "本次会话", "节点", "边",
}

# 关系是"对话行为"——描述的是聊天过程，不是事实
_CONVERSATION_VERBS = {
    "问", "问过", "问道", "询问", "答", "答道", "回答", "回", "回复",
    "说", "说过", "讲", "讲了", "提到", "提起", "聊", "聊到", "讨论", "谈到",
    "告诉", "告诉过", "夸", "夸过", "喊", "叫住", "提醒", "念叨",
    "记", "记下", "记进", "记录", "收录", "存", "存进", "写入", "灌",
    "看到", "看出来", "注意到", "想到", "觉得", "认为",
}

# 对话/图谱自身的管理性词汇：这些条目只是"关于记忆的记忆"
_META_TOKENS = {
    "对话内容", "对话流水", "这条", "那十条边", "条边", "节点", "边数",
    "待办", "提示词", "系统提示", "本次会话", "上文", "刚才说的",
}

# 数量/次数类碎片（"第三遍"、"两次"）
_QUANTITY_RE = re.compile(
    r"^第?[0-9一二三四五六七八九十百千万两]+(次|遍|条|个|句|回|天|年|月|日|元|秒|分钟|小时)?$"
)

# 疑问句残留
_QUESTION_RE = re.compile(r"[?？]\s*$|^(什么|怎么|为什么|哪|是否|多少)")

# 句读/从句特征：像"一句话"而不是"一个实体"
_CLAUSE_RE = re.compile(r"(的时候|之后|之前|的话|的时候|然后|但是|因为|所以|如果|虽然|而且)")

# 实体长度上限：中文实体几乎不会超过这个长度，超了基本是一整句话
MAX_ENTITY_LEN = 15
# 单字实体是合法的（猫/狗/书），垃圾单字由 _JUNK_SINGLE 黑名单处理
MIN_ENTITY_LEN = 1

# 关系同义词归一：同一事实常被抽成不同动词（"养"/"有"/"拥有"），
# 不归一会产生重复条目。只收高置信度、语义确定等价的映射。
_RELATION_SYNONYMS = {
    "养": "拥有", "饲养": "拥有", "有": "拥有", "拥有": "拥有",
    "叫做": "叫", "名叫": "叫", "名字是": "叫", "昵称是": "叫",
    "居住在": "住在", "住在": "住在", "居于": "住在",
    "从事": "做", "任职于": "做", "工作是": "做",
    "喜爱": "喜欢", "最爱": "最喜欢", "偏好": "喜欢",
    "研究方向为": "研究方向是", "研究领域是": "研究方向是",
    "属于": "是", "即为": "是",
}


@dataclass
class CurationResult:
    """一次审查的结果。"""

    kept: List[Quintuple] = field(default_factory=list)
    dropped: List[Tuple[Quintuple, str]] = field(default_factory=list)
    rewritten: List[Tuple[Quintuple, Quintuple, str]] = field(default_factory=list)

    @property
    def kept_count(self) -> int:
        return len(self.kept)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    def summary(self) -> Dict[str, int]:
        reasons: Dict[str, int] = {}
        for _, why in self.dropped:
            reasons[why] = reasons.get(why, 0) + 1
        return {
            "input": len(self.kept) + len(self.dropped),
            "kept": len(self.kept),
            "dropped": len(self.dropped),
            "rewritten": len(self.rewritten),
            "by_reason": reasons,
        }


# ---------------------------------------------------------------- 内部工具

def _clean(text: str) -> str:
    """去掉首尾空白、全角空格与多余的引号。"""
    if not isinstance(text, str):
        return ""
    t = text.replace("\u3000", " ").strip()
    t = t.strip("「」『』“”\"'《》<> ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _normalize_entity(name: str, user_name: str, ai_name: str) -> str:
    """把实体名归一化：人称 -> 规范名，别名 -> 规范名。"""
    n = _clean(name)
    if not n:
        return n
    if n in _USER_ALIASES:
        return user_name
    if n in _AI_ALIASES:
        return ai_name
    return n


def _reject_reason(head: str, rel: str, tail: str) -> Optional[str]:
    """返回拒收原因；None 表示放行。"""
    # 1) 空值
    if not head or not rel or not tail:
        return "空字段"

    # 2) 自环
    if head == tail:
        return "主体与客体相同"

    # 3) 纯代词 / 指示词 / 泛称
    if head in _PRONOUNS:
        return f"主体是代词/泛称: {head}"
    if tail in _PRONOUNS:
        return f"客体是代词/泛称: {tail}"

    # 3b) 单字垃圾（语气词/量词/虚词）—— 注意单字实体本身是允许的
    if head in _JUNK_SINGLE:
        return f"主体是无意义单字: {head}"
    if tail in _JUNK_SINGLE:
        return f"客体是无意义单字: {tail}"

    # 3c) 元话题作主体（图谱/记忆自身）
    if head in _META_HEADS:
        return f"主体是图谱/记忆自身: {head}"

    # 4) 长度
    if len(head) < MIN_ENTITY_LEN:
        return f"主体过短: {head}"
    if len(tail) < MIN_ENTITY_LEN:
        return f"客体过短: {tail}"
    if len(head) > MAX_ENTITY_LEN:
        return f"主体过长(疑似整句): {head[:12]}…"
    if len(tail) > MAX_ENTITY_LEN:
        return f"客体过长(疑似整句): {tail[:12]}…"

    # 5) 数量/次数碎片
    if _QUANTITY_RE.match(head):
        return f"主体是数量词: {head}"
    if _QUANTITY_RE.match(tail):
        return f"客体是数量词: {tail}"

    # 6) 疑问残留
    if _QUESTION_RE.search(head) or _QUESTION_RE.search(tail):
        return "疑问句残留"

    # 7) 关于记忆/图谱自身的管理性条目
    for tok in _META_TOKENS:
        if tok in head or tok in tail:
            return f"谈论对话/图谱自身: {tok}"

    # 8) 关系是对话行为
    if rel in _CONVERSATION_VERBS:
        return f"关系描述的是对话过程: {rel}"

    # 9) 从句/整句特征
    if _CLAUSE_RE.search(tail):
        return f"客体含从句: {tail[:12]}…"
    if _CLAUSE_RE.search(rel):
        return f"关系含从句: {rel[:12]}…"

    return None


# ---------------------------------------------------------------- 对外接口

def normalize_quintuple(
    q: Sequence[str],
    user_name: str = DEFAULT_USER_NAME,
    ai_name: str = DEFAULT_AI_NAME,
) -> Quintuple:
    """只做归一化，不判定去留。"""
    head, htype, rel, tail, ttype = (list(q) + ["", "", "", "", ""])[:5]
    rel_clean = _clean(rel)
    return (
        _normalize_entity(head, user_name, ai_name),
        _clean(htype),
        _RELATION_SYNONYMS.get(rel_clean, rel_clean),
        _normalize_entity(tail, user_name, ai_name),
        _clean(ttype),
    )


def curate_one(
    q: Sequence[str],
    user_name: str = DEFAULT_USER_NAME,
    ai_name: str = DEFAULT_AI_NAME,
) -> Tuple[Optional[Quintuple], str]:
    """审查单条。返回 (规范化后的五元组 或 None, 原因)。

    放行时原因字段为 "ok"；被改写时以 "ok(已归一化)" 标记。
    """
    norm = normalize_quintuple(q, user_name, ai_name)
    why = _reject_reason(norm[0], norm[2], norm[3])
    if why:
        return None, why
    original = tuple((list(q) + ["", "", "", "", ""])[:5])
    tag = "ok" if original == norm else "ok(已归一化)"
    return norm, tag


def curate(
    quintuples: Iterable[Sequence[str]],
    user_name: str = DEFAULT_USER_NAME,
    ai_name: str = DEFAULT_AI_NAME,
) -> CurationResult:
    """批量审查，返回保留/丢弃/改写明细。"""
    res = CurationResult()
    seen = set()
    for q in quintuples:
        original = tuple((list(q) + ["", "", "", "", ""])[:5])
        norm, why = curate_one(q, user_name, ai_name)
        if norm is None:
            res.dropped.append((original, why))
            continue
        if norm != original:
            res.rewritten.append((original, norm, "实体归一化"))
        if norm in seen:
            res.dropped.append((original, "重复条目"))
            continue
        seen.add(norm)
        res.kept.append(norm)
    return res


def curate_batch(quintuples, **kw) -> CurationResult:
    """curate 的别名，语义上用于清理存量数据。"""
    return curate(quintuples, **kw)


# ---------------------------------------------------------------- LLM 自我审查

# 交给模型的审查标准。要点：区分「稳定事实」与「对话过程/临时信息」。
_REVIEW_SYSTEM = """你是一个知识库管理员，负责审查「是否值得写入长期记忆」。

判断原则：**只要这条信息有可能是关于用户/世界的长期事实，就保留**；
只有明确属于下列「垃圾类别」时才丢弃。不要因为"信息量小"或"不够重要"就丢弃。

必须丢弃（仅这五类）：
1. 对话过程：谁问了什么、谁回答了什么、谁夸了谁、谁提醒了谁、谁确认了什么
2. 临时/易变信息：某时刻的天气、今天/某时段做了什么、当次情绪
3. 主观评价与比喻：「是今天最实的成果」「是基础设施」「冷水盆泼向用户」
4. 由代词/数量/指代拼成的碎片：「那个」「第三遍」「这个」「东西」
5. 关于记忆/图谱/对话自身的元讨论

应当保留（示例）：
- 用户 --最喜欢--> 杭州
- 用户 --拥有--> 猫 / 猫 --叫--> 小黑
- 用户 --研究方向是--> 知识图谱
- 技能框架 --覆盖--> 代码审查（项目结构的客观描述）
- 娜杰日达 --做--> 科研与工程搭档（稳定的角色设定）

对每一条给出保留或丢弃。只输出一个 JSON 数组，包含**保留**条目的序号（从 0 开始）。
例如保留第 0、3、5 条： [0, 3, 5]
若全部属于上述五类垃圾，输出： []
除 JSON 数组外不要输出任何其他内容。"""


async def review_with_llm(
    quintuples: Sequence[Quintuple],
    *,
    client=None,
    model: Optional[str] = None,
    timeout: float = 90.0,
) -> Tuple[List[Quintuple], List[Tuple[Quintuple, str]]]:
    """用一次模型调用批量「自我审查」，挑出值得长期记忆的条目。

    返回 (保留列表, [(被丢弃条目, 原因)])。

    设计取舍：
    - **批量**：一次调用审查整批，避免每条一次的网络往返。
    - **失败即放行**：模型不可用/输出不可解析时，保留规则层已通过的条目，
      绝不因为审查服务异常而丢用户数据。
    """
    items = [tuple(q) for q in quintuples]
    if not items:
        return [], []

    if client is None:
        try:
            from openai import AsyncOpenAI

            from core.system.config import config as _cfg
            client = AsyncOpenAI(api_key=_cfg.api.api_key, base_url=_cfg.api.base_url)
            model = model or _cfg.api.model
        except Exception:
            return list(items), []  # 无法构造客户端 -> 放行

    listing = "\n".join(
        f"{i}. ({q[0]}, {q[1]}, {q[2]}, {q[3]}, {q[4]})" for i, q in enumerate(items)
    )
    prompt = f"请审查以下五元组，返回值得写入长期记忆的序号数组：\n\n{listing}"

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            timeout=timeout,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception:
        return list(items), []  # 审查失败 -> 放行

    # 解析：从回复里抠出第一个 JSON 数组
    m = re.search(r"\[[^\[\]]*\]", content, re.S)
    if not m:
        return list(items), []
    try:
        import json as _json

        keep_idx = {int(x) for x in _json.loads(m.group(0))}
    except Exception:
        return list(items), []

    kept: List[Quintuple] = []
    dropped: List[Tuple[Quintuple, str]] = []
    for i, q in enumerate(items):
        if i in keep_idx:
            kept.append(q)
        else:
            dropped.append((q, "自我审查判定不值得长期记忆"))
    return kept, dropped


def curate_with_review_sync(
    quintuples: Sequence[Quintuple],
    *,
    use_llm: bool = True,
    **kw,
) -> CurationResult:
    """同步版：规则审查 + （可选）LLM 自我审查。供脚本/存量清理使用。"""
    import asyncio

    res = curate(quintuples, **kw)
    if not use_llm or not res.kept:
        return res

    try:
        kept, dropped = asyncio.run(review_with_llm(res.kept))
    except RuntimeError:
        # 已在事件循环中：开新线程跑
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            kept, dropped = ex.submit(
                lambda: asyncio.run(review_with_llm(res.kept))
            ).result()

    if dropped:
        res.dropped.extend(dropped)
        res.kept = kept
    return res



def report(result: CurationResult, max_items: int = 20) -> str:
    """把审查结果渲染成可读报告。"""
    s = result.summary()
    lines = [
        f"输入 {s['input']} 条 -> 保留 {s['kept']} 条，丢弃 {s['dropped']} 条，"
        f"归一化 {s['rewritten']} 条",
        "",
        "丢弃原因分布:",
    ]
    for why, c in sorted(s["by_reason"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {c:>4}  {why}")
    if result.rewritten:
        lines.append("")
        lines.append(f"归一化示例（最多 {max_items} 条）:")
        for old, new, _ in result.rewritten[:max_items]:
            lines.append(f"  {old[0]} --{old[2]}--> {old[3]}   =>   {new[0]} --{new[2]}--> {new[3]}")
    return "\n".join(lines)
