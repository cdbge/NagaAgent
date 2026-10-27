from pyvis.network import Network
import webbrowser
import json
import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 统一基于仓库根目录定位文件。
# 原实现用相对路径（"data/logs/..."），一旦进程 cwd 不是仓库根
# （例如从别处启动 main.py），就会静默读不到数据、生成空图。
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_KG_DIR = _REPO_ROOT / "data" / "logs" / "knowledge_graph"
_QUINTUPLES_JSON = _KG_DIR / "quintuples.json"
_GRAPH_HTML = _KG_DIR / "graph.html"

# 深色主题：与应用主界面一致（窗口背景为 QColor(25,25,25,WINDOW_BG_ALPHA)）。
# 页面背景做成透明，让应用自身背景透出来，因此文字必须用浅色，否则深底上看不见。
# 配色以"在深浅不一的壁纸上都能看清"为准，并给文字加深色描边。
_THEME = {
    "bg": "transparent",
    "fg": "#F2F4F8",          # 节点名（近白，保证可读）
    "edge": "#7C838F",        # 连线（比文字暗一档，避免喧宾夺主）
    "edge_label": "#D2D7E0",  # 关系名（比连线亮，保证读得出）
    "stroke": "#141414",      # 文字描边，保证在任何底色上都清晰
}

# pyvis 模板只监听 stabilizationProgress 更新进度条，**没有 stabilized 处理**，
# 结果进度条停在 100% 永不消失，遮在图上让人误以为"没加载出来/是空的"。
# 这里给生成的 HTML 补一段收尾脚本：稳定后淡出进度条，并有超时兜底。
_LOADINGBAR_FIX = """
<script>
(function () {
  function hide() {
    var el = document.getElementById('loadingBar');
    if (el) {
      el.style.opacity = 0;
      setTimeout(function () { el.style.display = 'none'; }, 400);
    }
  }
  function fitNicely() {
    // 画布改成填满容器后，vis 会自动缩放到「刚好铺满」，节点被放得很大、
    // 标签互相压住。这里限制最大缩放，留出留白。
    try {
      network.fit({ maxZoomLevel: 0.7, animation: { duration: 400 } });
    } catch (e) {
      try { network.fit(); } catch (e2) {}
    }
  }
  function attach() {
    if (typeof network !== 'undefined' && network && network.on) {
      network.on('stabilized', function () { fitNicely(); hide(); });
      // 兜底：物理布局迟迟不收敛时也让图能看清
      setTimeout(function () { fitNicely(); hide(); }, 4000);
    } else {
      setTimeout(attach, 100);
    }
  }
  attach();
})();
</script>
"""


def _inject_loadingbar_fix(html: str) -> str:
    """收尾处理生成的 HTML：

    1. 插入进度条收尾脚本（否则一直停在 100% 遮挡图形）
    2. 去掉 pyvis 模板自带的 bootstrap CDN 引用并补一段等效的最小内联样式，
       使文件**完全自包含**、断网也能正常查看（渲染库 vis-network 已内联）。
    """
    # --- 去掉 bootstrap 的 CDN <link>/<script> ---
    html = re.sub(
        r'<link[^>]*href="https://cdn\.jsdelivr\.net/npm/bootstrap[^"]*"[^>]*>\s*',
        "", html)
    html = re.sub(
        r'<script[^>]*src="https://cdn\.jsdelivr\.net/npm/bootstrap[^"]*"[^>]*>\s*</script>\s*',
        "", html)

    # --- 补一段最小的替代样式 ---
    # 目标是「纯画布 + 深色主题适配」：不要边框、不要滚动条、画布填满可视区，
    # 且背景透明 —— 让应用自身的深色背景透出来，避免突兀的白底。
    # pyvis 默认写死 1600px 高、给 body 留边距、并用白底。
    # 注意：这里用占位符替换而不是 % 格式化 —— CSS 里大量 "100%" 会被
    # % 格式化误判为格式说明符（ValueError: unsupported format character）。
    minimal_css = (
        "<style>\n"
        "  html, body { height: 100%; overflow: hidden; background: transparent; }\n"
        "  body { font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;"
        " margin: 0; padding: 0; box-sizing: border-box; }\n"
        "  #mynetwork { width: 100% !important; height: 100vh !important;"
        " border: none !important; border-radius: 0 !important; background: transparent !important; }\n"
        "  .card { border: none; padding: 0; margin: 0; background: transparent; }\n"
        "  h1, h2, h3 { margin: 0 0 8px; font-weight: 600; color: __FG__; }\n"
        "</style>\n"
    ).replace("__FG__", _THEME["fg"])

    idx = html.rfind("</head>")
    if idx != -1:
        html = html[:idx] + minimal_css + html[idx:]

    idx = html.rfind("</body>")
    if idx == -1:
        return html + _LOADINGBAR_FIX
    return html[:idx] + _LOADINGBAR_FIX + html[idx:]


def load_quintuples_from_json():
    """
    直接从JSON文件中读取五元组数据，解耦数据库依赖
    """
    try:
        json_file = _QUINTUPLES_JSON
        print(f"尝试读取 {json_file} 文件...")
        if not os.path.exists(json_file):
            print(f"错误：{json_file} 文件不存在！")
            return set()
            
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"JSON文件读取成功，包含 {len(data)} 条记录")
            result = set(tuple(t) for t in data)
            print(f"转换为集合后包含 {len(result)} 条唯一记录")
            return result
    except FileNotFoundError:
        print("错误：找不到 quintuples.json 文件")
        return set()
    except json.JSONDecodeError as e:
        print(f"错误：JSON文件格式错误 - {e}")
        return set()
    except Exception as e:
        print(f"错误：读取文件时发生异常 - {e}")
        return set()

def visualize_quintuples():
    """
    直接从JSON文件中读取所有五元组，并生成可视化图谱 graph.html
    解耦版本：不依赖Neo4j数据库，直接从JSON文件读取数据
    """
    try:
        print("开始读取五元组数据...")
        quintuples = load_quintuples_from_json()
        print(f"读取到 {len(quintuples)} 条原始数据")
        
        if not quintuples:
            logger.warning("从JSON文件中未获取到任何五元组，无法生成可视化图谱")
            print("未获取到任何五元组，无法生成图谱。")
            return
        
        logger.info(f"从JSON文件获取到 {len(quintuples)} 条五元组进行可视化")

        # 过滤非法五元组
        print("开始过滤无效五元组...")
        valid_quintuples = [
            t for t in quintuples
            if isinstance(t, tuple) and len(t) == 5 and all(isinstance(x, str) and x.strip() for x in t)
        ]
        print(f"过滤后剩余 {len(valid_quintuples)} 条有效五元组")
        
        if not valid_quintuples:
            print("错误：没有有效的五元组数据！")
            return
        
        print("开始创建网络图...")
        # cdn_resources="in_line"：把 vis-network 渲染库**内联**进 HTML。
        # 原实现走 CDN（cdnjs/jsdelivr），在国内网络或离线环境下脚本加载失败，
        # 页面就是一片空白 —— 数据其实已内嵌在 HTML 里，只是没有库去渲染它。
        # 内联后 HTML 完全自包含，双击即可查看，无需联网。
        net = Network(height='100vh', width='100%', notebook=False,
                      cdn_resources='in_line',
                      bgcolor=_THEME['bg'],          # 透明，避免白色底
                      font_color=_THEME['fg'])       # 浅色，深底上可读
        net.use_template = False
        net.barnes_hut()
        # 布局调参说明：
        # 原为 gravitationalConstant=-8000 / springConstant=0.04，斥力强而弹簧弱，
        # 导致彼此不连通的孤立节点（记忆里大量两节点小片段）被推得极远，
        # 主图缩在角落。这里减弱斥力、增强弹簧，并加大 avoidOverlap 与弹簧长度，
        # 让节点之间有足够间距 —— 否则标签会互相压住（如「代码审查」盖住
        # 「翻译真实性验证」）。
        net.set_options("""
        var options = {
          "physics": {
            "barnesHut": {
              "gravitationalConstant": -3000,
              "springLength": 200,
              "springConstant": 0.05,
              "damping": 0.6,
              "avoidOverlap": 0.6
            },
            "minVelocity": 0.5,
            "maxVelocity": 25,
            "stabilization": {
              "enabled": true,
              "iterations": 600,
              "updateInterval": 25
            }
          },
          "nodes": {
            "font": {"size": 17, "color": "%(fg)s", "strokeWidth": 3, "strokeColor": "%(stroke)s"},
            "borderWidth": 2,
            "borderWidthSelected": 3
          },
          "edges": {
            "color": {"color": "%(edge)s", "highlight": "%(fg)s"},
            "font": {"size": 14, "color": "%(edge_label)s", "strokeWidth": 3, "strokeColor": "%(stroke)s"},
            "smooth": {"type": "continuous"}
          },
          "interaction": {"hover": true, "tooltipDelay": 120}
        }
        """ % _THEME)

        added_nodes = set()
        # 定义不同实体类型的颜色
        type_colors = {
            '人物': '#FF6B6B',
            '地点': '#4ECDC4', 
            '组织': '#45B7D1',
            '物品': '#96CEB4',
            '概念': '#FFEAA7',
            '时间': '#DDA0DD',
            '事件': '#F4A460',
            '活动': '#FFB347'
        }
        default_color = '#CCCCCC'
        
        print("开始构建图谱节点和边...")
        edge_count = 0
        for head, head_type, rel, tail, tail_type in valid_quintuples:
            # 添加主体节点
            if head not in added_nodes:
                head_color = type_colors.get(head_type, default_color)
                net.add_node(head, label=f"{head}\n({head_type})", color=head_color,
                             font={'size': 20, 'color': _THEME['fg']})
                added_nodes.add(head)
            
            # 添加客体节点
            if tail not in added_nodes:
                tail_color = type_colors.get(tail_type, default_color)
                net.add_node(tail, label=f"{tail}\n({tail_type})", color=tail_color,
                             font={'size': 20, 'color': _THEME['fg']})
                added_nodes.add(tail)
            
            # 添加关系边
            net.add_edge(head, tail, label=rel, length=120,
                         color={'color': _THEME['edge']},
                         font={'size': 17, 'color': _THEME['edge_label']})
            edge_count += 1

        print(f"图谱构建完成：{len(added_nodes)} 个节点，{edge_count} 条边")
        print("正在生成HTML文件...")
        # 确保目录存在
        os.makedirs(_KG_DIR, exist_ok=True)
        
        html_file = _GRAPH_HTML
        # 不用 net.write_html()：它内部是 open(name, "w+")，**未指定编码**，
        # 在中文 Windows 上按 GBK 写，遇到内联库里的非 GBK 字符会直接
        # UnicodeEncodeError。这里取 HTML 字符串后自行以 UTF-8 落盘。
        html_content = net.generate_html(str(html_file))
        html_content = _inject_loadingbar_fix(html_content)
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML文件生成完成：{html_file}")

        try:
            print("尝试打开浏览器...")
            # 获取正确的绝对路径
            abs_html_path = os.path.abspath(html_file)
            webbrowser.open("file:///" + abs_html_path)
            print("浏览器打开成功！")
        except Exception as e:
            print(f"无法自动打开浏览器：{e}")

        print("知识图谱已生成：graph.html，请手动打开查看。")
        logger.info("知识图谱可视化完成，文件 graph.html 已生成")

    except Exception as e:
        print(f"发生异常：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        logger.error(f"可视化五元组失败: {e}")
        print(f"生成知识图谱失败: {e}")


# 添加主函数用于测试
if __name__ == "__main__":
    print("=" * 50)
    print("开始测试可视化功能")
    print("=" * 50)
    visualize_quintuples()