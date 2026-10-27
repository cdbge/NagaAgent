import json
import logging
import sys
import os
import time
import asyncio
from typing import List
from pydantic import BaseModel

# 添加项目根目录到路径，以便导入config
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from core.system.config import config
from openai import OpenAI, AsyncOpenAI

# 初始化OpenAI客户端
client = OpenAI(
    api_key=config.api.api_key,
    base_url=config.api.base_url
)

async_client = AsyncOpenAI(
    api_key=config.api.api_key,
    base_url=config.api.base_url
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 结构化输出（response_format / beta.chat.completions.parse）在当前 DeepSeek 模型上
# 会直接返回 400 "This response_format type is unavailable now"。旧实现对此仍然重试
# 3 次，每次都要等一次网络往返，抽取被白白拖慢。这里记住"不支持"这一事实，
# 本进程内后续直接走传统 JSON 解析路径。
_STRUCTURED_OUTPUT_SUPPORTED = True
_STRUCTURED_UNSUPPORTED_MARKERS = (
    "response_format",
    "unavailable now",
    "does not support",
    "not supported",
)


# 定义五元组的Pydantic模型
class Quintuple(BaseModel):
    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str


class QuintupleResponse(BaseModel):
    quintuples: List[Quintuple]


async def extract_quintuples_async(text):
    """异步版本的五元组提取"""
    # 首先尝试使用结构化输出
    return await _extract_quintuples_async_structured(text)


async def _extract_quintuples_async_structured(text):
    """使用结构化输出的异步五元组提取"""
    # 已确认当前模型不支持结构化输出 -> 直接走传统方法
    if not _STRUCTURED_OUTPUT_SUPPORTED:
        return await _extract_quintuples_async_fallback(text)

    system_prompt = f"""
你是一个专业的中文文本信息抽取专家。你的任务是从给定的中文文本中抽取五元组关系。
五元组格式为：(主体, 主体类型, 动作, 客体, 客体类型)。

类型包括但不限于：人物、地点、组织、物品、概念、时间、事件、活动等。

例如：
输入：小明在公园里踢足球。
应该提取出：
- 主体：小明，类型：人物，动作：踢，客体：足球，类型：物品
- 主体：小明，类型：人物，动作：在，客体：公园，类型：地点
{_quality_rules_block()}"""

    # 重试机制配置
    max_retries = 3

    for attempt in range(max_retries + 1):
        logger.info(f"尝试使用结构化输出提取五元组 (第{attempt + 1}次)")

        try:
            # 尝试使用结构化输出
            completion = await async_client.beta.chat.completions.parse(
                model=config.api.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请从以下文本中提取五元组：\n\n{text}"}
                ],
                response_format=QuintupleResponse,
                max_tokens=config.api.max_tokens,
                temperature=0.3,
                timeout=600 + (attempt * 20)
            )

            # 解析结果
            result = completion.choices[0].message.parsed
            quintuples = []
            
            for q in result.quintuples:
                quintuples.append((
                    q.subject, q.subject_type, 
                    q.predicate, q.object, q.object_type
                ))
            
            logger.info(f"结构化输出成功，提取到 {len(quintuples)} 个五元组")
            return quintuples

        except Exception as e:
            logger.warning(f"结构化输出失败: {str(e)}")
            if attempt == max_retries - 1:  # 最后一次尝试，回退到传统方法
                logger.info("回退到传统JSON解析方法")
                return await _extract_quintuples_async_fallback(text)
            elif attempt < max_retries:
                await asyncio.sleep(1 + attempt)

    return []


def _quality_rules_block() -> str:
    """抽取质量约束（治本措施）。

    旧提示词只写「提取所有可以识别出的五元组」，导致把**对话过程本身**也收进图谱。
    对真实数据的实测：256 条里 203 条含 <=3 字的碎片，67 条主体是代词，
    25 条在谈论对话/图谱自身。因此在提示词里把「什么值得记」写死。
    """
    return """
【只提取长期有效的事实，不要提取对话过程】
值得提取：用户的属性与偏好（姓名/职业/研究方向/所在地/喜好/习惯/拥有的东西）、
稳定的人际关系（家人/朋友/同事/宠物及名字）、长期项目与领域知识。
不要提取：
- 谁问了什么、谁回答了什么、谁夸了谁、谁提醒了谁（这些是对话过程）
- 临时或易变信息（此刻的天气、今天做了什么、某一时段的情绪）
- 主观评价与比喻（例如「是今天最实的成果」）
- 由代词、数量词、指代拼起来的碎片（例如「那个」「第三遍」「这个」）

【实体必须是具体名词，且必须消解代词】
- 用户说的「我/你」一律写成「用户」；助手说的「我」写成「娜杰日达」
- 禁止把「你」「我」「他」「这个」「那个」「东西」「事情」等作为主体或客体
- 主体与客体都必须是有意义的实体名，长度 2~15 字；不要用整句话当实体
- 同一实体必须用统一的名称（例如统一写「娜杰日达」，不要写成「娜杰达」「娜日达」）

【宁可少提，不要凑数】
如果这段对话里没有值得长期记住的事实，就返回空数组 []。
提取 1~3 条高质量事实，远好于提取 10 条碎片。
"""


async def _extract_quintuples_async_fallback(text):
    """传统JSON解析的异步五元组提取（回退方案）"""
    prompt = f"""
从以下中文对话中抽取值得长期记忆的事实，用五元组（主体-主体类型-关系-客体-客体类型）表示，
以 JSON 数组格式返回。

类型包括但不限于：人物、地点、组织、物品、概念、时间、事件、活动等。

例如：
输入：用户：我最喜欢的城市是杭州，我养了一只叫小黑的猫。
输出：[["用户", "人物", "最喜欢", "杭州", "地点"], ["用户", "人物", "养", "猫", "动物"], ["猫", "动物", "叫", "小黑", "名称"]]

反例（不要这样提取）：
输入：用户：镇江今天天气怎么样？  助手：今天晴，23度。
输出：[]            ← 天气是临时信息，且「问天气」是对话过程，都不该记
{_quality_rules_block()}
请从以下文本中提取：
{text}

除了JSON数据，请不要输出任何其他数据，例如：```、```json、以下是我提取的数据：。
"""

    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            response = await async_client.chat.completions.create(
                model=config.api.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=config.api.max_tokens,
                temperature=0.3,
                timeout=600 + (attempt * 20)
            )
            
            content = response.choices[0].message.content.strip()
            
            # 尝试解析JSON
            try:
                quintuples = json.loads(content)
                logger.info(f"传统方法成功，提取到 {len(quintuples)} 个五元组")
                return [tuple(t) for t in quintuples if len(t) == 5]
            except json.JSONDecodeError:
                logger.error(f"JSON解析失败，原始内容: {content[:200]}")
                # 尝试直接提取数组
                if '[' in content and ']' in content:
                    start = content.index('[')
                    end = content.rindex(']') + 1
                    quintuples = json.loads(content[start:end])
                    return [tuple(t) for t in quintuples if len(t) == 5]
                raise

        except Exception as e:
            logger.error(f"传统方法提取失败: {str(e)}")
            if attempt < max_retries:
                await asyncio.sleep(1 + attempt)

    return []


def extract_quintuples(text):
    """同步版本的五元组提取"""
    # 首先尝试使用结构化输出
    return _extract_quintuples_structured(text)


def _extract_quintuples_structured(text):
    """使用结构化输出的同步五元组提取"""
    global _STRUCTURED_OUTPUT_SUPPORTED

    # 已确认当前模型不支持结构化输出 -> 直接走传统方法，省掉无谓的网络往返
    if not _STRUCTURED_OUTPUT_SUPPORTED:
        return _extract_quintuples_fallback(text)

    system_prompt = f"""
你是一个专业的中文文本信息抽取专家。你的任务是从给定的中文文本中抽取五元组关系。
五元组格式为：(主体, 主体类型, 动作, 客体, 客体类型)。

类型包括但不限于：人物、地点、组织、物品、概念、时间、事件、活动等。

例如：
输入：小明在公园里踢足球。
应该提取出：
- 主体：小明，类型：人物，动作：踢，客体：足球，类型：物品
- 主体：小明，类型：人物，动作：在，客体：公园，类型：地点
{_quality_rules_block()}"""

    # 重试机制配置
    max_retries = 3

    for attempt in range(max_retries + 1):
        logger.info(f"尝试使用结构化输出提取五元组 (第{attempt + 1}次)")

        try:
            # 尝试使用结构化输出
            completion = client.beta.chat.completions.parse(
                model=config.api.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请从以下文本中提取五元组：\n\n{text}"}
                ],
                response_format=QuintupleResponse,
                max_tokens=config.api.max_tokens,
                temperature=0.3,
                timeout=600 + (attempt * 20)
            )

            # 解析结果
            result = completion.choices[0].message.parsed
            quintuples = []
            
            for q in result.quintuples:
                quintuples.append((
                    q.subject, q.subject_type, 
                    q.predicate, q.object, q.object_type
                ))
            
            logger.info(f"结构化输出成功，提取到 {len(quintuples)} 个五元组")
            return quintuples

        except Exception as e:
            msg = str(e)
            logger.warning(f"结构化输出失败: {msg}")

            # 模型不支持结构化输出：不要再重试，直接回退，并记住结论
            if any(marker in msg.lower() for marker in _STRUCTURED_UNSUPPORTED_MARKERS):
                _STRUCTURED_OUTPUT_SUPPORTED = False
                logger.info("当前模型不支持结构化输出，改用传统JSON解析方法（后续不再尝试）")
                return _extract_quintuples_fallback(text)

            if attempt == max_retries - 1:  # 最后一次尝试，回退到传统方法
                logger.info("回退到传统JSON解析方法")
                return _extract_quintuples_fallback(text)
            elif attempt < max_retries:
                time.sleep(1 + attempt)

    return []


def _extract_quintuples_fallback(text):
    """传统JSON解析的同步五元组提取（回退方案）"""
    prompt = f"""
从以下中文文本中抽取五元组（主语-主语类型-谓语-宾语-宾语类型）关系，以 JSON 数组格式返回。

类型包括但不限于：人物、地点、组织、物品、概念、时间、事件、活动等。

例如：
输入：小明在公园里踢足球。
输出：[["小明", "人物", "踢", "足球", "物品"], ["小明", "人物", "在", "公园", "地点"]]

请从文本中提取所有可以识别出的五元组：
{text}

除了JSON数据，请不要输出任何其他数据，例如：```、```json、以下是我提取的数据：。
"""

    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config.api.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=config.api.max_tokens,
                temperature=0.5,
                timeout=600 + (attempt * 20)
            )

            content = response.choices[0].message.content.strip()
            
            # 尝试解析JSON
            try:
                quintuples = json.loads(content)
                logger.info(f"传统方法成功，提取到 {len(quintuples)} 个五元组")
                return [tuple(t) for t in quintuples if len(t) == 5]
            except json.JSONDecodeError:
                logger.error(f"JSON解析失败，原始内容: {content[:200]}")
                # 尝试直接提取数组
                if '[' in content and ']' in content:
                    start = content.index('[')
                    end = content.rindex(']') + 1
                    quintuples = json.loads(content[start:end])
                    return [tuple(t) for t in quintuples if len(t) == 5]
                raise

        except Exception as e:
            logger.error(f"传统方法提取失败: {str(e)}")
            if attempt < max_retries:
                time.sleep(1)

    return []