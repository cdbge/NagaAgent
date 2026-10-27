# agent_weather_time.py # 天气和时间查询Agent
import json # 导入json模块
import logging
import aiohttp
from servers.mcpserver.base_agent import Agent, ComputerTool
import requests
import re # 用于正则解析
from datetime import datetime # 用于日期处理

from servers.mcpserver.agent_weather_time.city_codes import codes_map

logger = logging.getLogger(__name__)

IPIP_URL = "https://myip.ipip.net/" # 统一配置

# wttr.in 返回英文天气描述，映射为中文，使备用源与主源输出风格一致
_WEATHER_DESC_ZH = {
    "Sunny": "晴", "Clear": "晴", "Partly cloudy": "多云", "Cloudy": "阴",
    "Overcast": "阴", "Mist": "薄雾", "Fog": "雾", "Haze": "霾",
    "Light rain": "小雨", "Patchy rain possible": "局部有雨",
    "Patchy rain nearby": "周边有雨", "Moderate rain": "中雨",
    "Heavy rain": "大雨", "Light drizzle": "毛毛雨", "Rain": "雨",
    "Light snow": "小雪", "Moderate snow": "中雪", "Heavy snow": "大雪",
    "Snow": "雪", "Sleet": "雨夹雪", "Thundery outbreaks possible": "可能有雷雨",
    "Patchy light rain with thunder": "雷阵雨", "Light freezing rain": "冻雨",
    "Blowing snow": "吹雪", "Blizzard": "暴风雪",
}

class WeatherTimeTool:
    """天气和时间工具类"""
    def __init__(self):
        self._ip_info = None # 缓存IP信息
        self._local_ip = None # 本地IP
        self._local_city = None # 本地城市
        self._get_local_ip_and_city() # 初始化时获取本地IP和城市
        import asyncio
        try:
            # 使用新的API检查事件循环状态 # 右侧注释
            try:
                loop = asyncio.get_running_loop()
                # 有运行中的事件循环，创建异步任务
                asyncio.create_task(self._preload_ip_info())
            except RuntimeError:
                # 没有运行中的事件循环
                self._ip_info = None # 不再异步获取IP
        except Exception:
            self._ip_info = None

    def _get_local_ip_and_city(self):
        """同步获取本地IP和城市"""
        try:
            resp = requests.get(IPIP_URL, timeout=5)
            resp.encoding = 'utf-8'
            html = resp.text
            match = re.search(r"当前 IP：([\d\.]+)\s+来自于：(.+?)\s{2,}", html)
            if match:
                self._local_ip = match.group(1)
                self._local_city = match.group(2)
            else:
                self._local_ip = None
                self._local_city = None
        except Exception:
            self._local_ip = None
            self._local_city = None

    async def _preload_ip_info(self):
        pass # 兼容保留，不再异步获取IP

    def _resolve_city_code(self, province: str, city_name: str, raw: str):
        """把 LLM 传来的城市参数解析为 codes_map 的键。

        codes_map 的键是"省市拼接"形式（如 '江苏镇江'、'北京北京'）。
        LLM 实际会传来各种写法，旧代码只支持严格的"省 市"（空格分隔），
        其它写法会直接 KeyError（错误信息还会变成生僻的 "'镇江江苏'"）：

            '江苏 镇江'   -> 拼接后命中
            '镇江 江苏'   -> 省市顺序反了，需要交换
            '江苏镇江'    -> 无空格，本身就是键
            '镇江'        -> 只有市名，需要用后缀匹配
            '北京'        -> 直辖市，需要补成 '北京北京'

        返回 (city_code, 规范城市名)；找不到时返回 (None, None)。
        """
        candidates = []

        def add(value: str):
            value = (value or "").strip().replace(" ", "").replace("　", "")
            if value and value not in candidates:
                candidates.append(value)

        raw_clean = (raw or "").strip()

        # 1) 原始值（去掉空格后）直接作为候选
        add(raw_clean)
        # 2) province + city 顺序拼接
        add(f"{province}{city_name}")
        # 3) 反序拼接（LLM 常把"市 省"写反）
        add(f"{city_name}{province}")

        # 4) 空格分隔的情况：尝试两种顺序
        parts = raw_clean.split()
        if len(parts) >= 2:
            add(f"{parts[0]}{parts[-1]}")
            add(f"{parts[-1]}{parts[0]}")

        # 逐候选精确匹配
        for cand in candidates:
            if cand in codes_map:
                return codes_map[cand], cand

        # 5) 无空格且只有一个地名时用后缀匹配（如 '镇江' -> '江苏镇江'）
        tokens = [t for t in ([raw_clean] + parts if parts else [raw_clean]) if t]
        for token in tokens:
            for suffix in ("市", "省", "自治区", "特别行政区"):
                if token.endswith(suffix) and len(token) > len(suffix):
                    token = token[: -len(suffix)]
            hits = [k for k in codes_map if k.endswith(token)]
            if len(hits) == 1:
                return codes_map[hits[0]], hits[0]
            # 直辖市：'北京' -> '北京北京'
            doubled = token + token
            if doubled in codes_map:
                return codes_map[doubled], doubled

        return None, None

    async def get_weather(self, code, city_name=None):
        """获取天气：主源 itboy，失败时降级到 wttr.in。

        返回 (now, 未来3天, 未来15天)。

        为什么要降级：itboy（t.weather.itboy.net）是免费第三方接口，
        属于单点依赖，挂了整个天气功能就不可用。wttr.in 同样免 key，
        可作兜底。两者数据形状不同，这里统一归一化成 itboy 的字段名，
        使上层（包括读 JSON 的模型）无需区分数据来源。
        """
        try:
            return await self._get_weather_itboy(code)
        except Exception as exc:
            logger.warning(f"[天气] 主源 itboy 失败（{type(exc).__name__}: {exc}），尝试备用源")
            if not city_name:
                raise
            return await self._get_weather_wttr(city_name)

    async def _get_weather_itboy(self, code):
        """主源：itboy 接口，返回实况天气+未来3天预报。"""
        url = f'http://t.weather.itboy.net/api/weather/city/{code}'
        # 必须设超时：原实现不设超时，接口无响应时请求会一直挂着
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)

                body: dict = data['data']
                now = {}

                for k, v in body.items():
                    if k == 'forecast':
                        continue
                    now[k] = v  # 把forecast外的数据整合再一起

                now['weather'] = body['forecast'][0]
                return now, body['forecast'][:3], body['forecast']

    async def _get_weather_wttr(self, city_name):
        """备用源：wttr.in（免 API key），输出归一化成 itboy 的字段名。"""
        url = f'https://wttr.in/{city_name}?format=j1'
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {'User-Agent': 'curl/8.0'}  # wttr.in 对默认 UA 有时返回 HTML
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)

        cur = (data.get('current_condition') or [{}])[0]
        days = data.get('weather') or []
        if not days:
            raise RuntimeError('wttr.in 未返回预报数据')

        def _desc(node):
            arr = node.get('weatherDesc') or [{}]
            return _WEATHER_DESC_ZH.get((arr[0].get('value') or '').strip(),
                                        arr[0].get('value') or '')

        def _day_desc(day):
            """每日天气描述在 hourly 里（wttr.in 的 day 对象没有 weatherDesc）。

            优先取正午 12:00 那条，最能代表全天；取不到再退到中间/首条。
            """
            hourly = day.get('hourly') or []
            if not hourly:
                return ''
            pick = None
            for e in hourly:
                if str(e.get('time')) == '1200' and e.get('weatherDesc'):
                    pick = e
                    break
            if pick is None:
                mid = hourly[len(hourly) // 2]
                pick = mid if mid.get('weatherDesc') else hourly[0]
            return _desc(pick)

        def _mk(day):
            astro = (day.get('astronomy') or [{}])[0]
            return {
                'date': day.get('date', ''),
                'ymd': day.get('date', ''),
                'week': '',
                'high': f"高温 {day.get('maxtempC', '')}℃",
                'low': f"低温 {day.get('mintempC', '')}℃",
                'type': _day_desc(day),
                'fx': ' '.join(filter(None, [cur.get('winddir16Point', '')])),
                'fl': f"{cur.get('windspeedKmph', '')}km/h",
                'sunrise': astro.get('sunrise', ''),
                'sunset': astro.get('sunset', ''),
                'notice': '（数据来源：wttr.in）',
            }

        forecast = [_mk(d) for d in days]

        now = {
            'wendu': cur.get('temp_C', ''),
            'shidu': f"{cur.get('humidity', '')}%",
            'pm25': cur.get('pm2_5', ''),
            'quality': '',
            'ganmao': '',
            'weather': forecast[0] if forecast else {},
            'source': 'wttr.in',
            'feels_like': cur.get('FeelsLikeC', ''),
        }
        # wttr.in 只给 3 天，就当作 3 天与 15 天的共同数据
        return now, forecast[:3], forecast

    async def handle(self, action=None, ip=None, city=None, query=None, format=None, **kwargs):
        """统一处理入口，支持LLM传入city参数或自动识别本地城市"""  # 右侧注释
        # 优先使用LLM传入的city参数，如果没有则使用本地城市 # 右侧注释
        if city and city.strip():
            # LLM传入了city参数，直接使用
            city_str = city.strip()
            province, city_name = city_str, city_str
            # 尝试解析省市格式
            match = re.match(r"^([\u4e00-\u9fa5]+) ([\u4e00-\u9fa5]+)$", city_str)
            if match:
                province = match.group(1)
                city_name = match.group(2)
            else:
                parts = city_str.split()
                if len(parts) >= 2:
                    province = parts[-2]
                    city_name = parts[-1]
                else:
                    province = ''
                    city_name =''
        else:
            # LLM没有传入city参数，使用本地城市作为默认值
            city_str = getattr(self, '_local_city', '') or ''
            if city_str.startswith('中国'):
                city_str = city_str[2:].strip()
            province, city_name = city_str, city_str
            if city_str:
                match = re.match(r"^([\u4e00-\u9fa5]+) ([\u4e00-\u9fa5]+)$", city_str)
                if match:
                    province = match.group(1)
                    city_name = match.group(2)
                else:
                    parts = city_str.split()
                    if len(parts) >= 2:
                        province = parts[-2]
                        city_name = parts[-1]
                    else:
                        province = ''
                        city_name = ''

        # 查询城市代码
        city_code, resolved = self._resolve_city_code(province, city_name, city_str)

        if not city_code:
            return {'status': 'error', 'message': (
                f'未找到城市编码或该城市不存在: {city_str!r}。'
                'city 参数请用「省 市」格式，如: 江苏 镇江、湖北 武汉；'
                '直辖市重复市名，如: 北京 北京'
            )}

        # 用解析到的规范市名，供后续返回展示
        city_name = resolved or city_name

        # 备用源 wttr.in 需要城市名而非城市编码，故一并传入
        now, d3, d15 = await self.get_weather(city_code, city_name=city_name)

        # 今日天气查询，只返回今日天气数据 # 右侧注释
        if action in ['today_weather', 'current_weather', 'today']:
            return {'city': city_name, 'response': now}

        # 未来天气查询，返回未来15天预报数据 # 右侧注释
        elif action in ['forecast_weather', 'future_weather', 'forecast', 'weather_forecast']:
            return {'city': city_name, 'response': d15}

        elif action in ['time', 'get_time', 'current_time']:
            # 时间查询
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return {
                'status': 'ok',
                'message': '当前系统时间',
                'data': {
                    'time': current_time,
                    'city': city_name,
                    'province': province
                }
            }
        else:
            return {'status': 'error', 'message': f'未知操作: {action}'}
class WeatherTimeAgent(Agent):
    """天气和时间Agent"""
    def __init__(self):
        self._tool = WeatherTimeTool() # 预加载
        super().__init__(
            name="WeatherTime Agent", # Agent名称
            instructions="天气和时间智能体", # 角色描述
            tools=[ComputerTool(self._tool)], # 注入工具
            model="weather-time-use-preview" # 使用统一模型
        )
        import sys
        ip_str = getattr(self._tool, '_local_ip', '未获取到IP')  # 直接用本地IP
        city_str = getattr(self._tool, '_local_city', '未知城市') # 获取本地城市
        sys.stderr.write(f'✅ WeatherTimeAgent初始化完成，登陆地址：{city_str}\n')

    async def handle_handoff(self, task: dict) -> str:
        try:
            # 只认tool_name参数
            action = task.get("tool_name")
            if not action:
                return json.dumps({"status": "error", "message": "缺少tool_name参数", "data": {}}, ensure_ascii=False)
            ip = task.get("ip")
            city = task.get("city")
            query = task.get("query")
            format = task.get("format")
            result = await self._tool.handle(action, ip, city, query, format)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "data": {}}, ensure_ascii=False)