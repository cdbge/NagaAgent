import os
import logging
from pathlib import Path
from core.system.config import config
from . import chat

logger = logging.getLogger(__name__)

# 基于仓库根目录定位，避免 cwd 不是仓库根时静默找不到文件
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_KG_DIR = _REPO_ROOT / "data" / "logs" / "knowledge_graph"


class MindmapTool():
    def __init__(self, window):
        self.window = window
        
    def open_mind_map(self):
        """打开心智云图"""
        try:
            # 检查是否存在知识图谱文件
            graph_file = str(_KG_DIR / "graph.html")
            quintuples_file = str(_KG_DIR / "quintuples.json")
            
            # 如果quintuples.json存在，删除现有的graph.html并重新生成
            if os.path.exists(quintuples_file):
                # 如果graph.html存在，先删除它
                if os.path.exists(graph_file):
                    try:
                        os.remove(graph_file)
                        logger.debug(f"已删除旧的graph.html文件")
                    except Exception as e:
                        logger.error(f"删除graph.html文件失败: {e}")
                
                # 生成新的HTML
                chat.add_user_message("系统", "🔄 正在生成心智云图...")
                try:
                    from core.summer_memory.quintuple_visualize_v2 import visualize_quintuples
                    visualize_quintuples()
                    if os.path.exists(graph_file):
                        import webbrowser
                        # graph_file 已是基于仓库根的绝对路径
                        webbrowser.open(Path(graph_file).as_uri())
                        chat.add_user_message("系统", "🧠 心智云图已生成并打开")
                    else:
                        chat.add_user_message("系统", "❌ 心智云图生成失败")
                except Exception as e:
                    chat.add_user_message("系统", f"❌ 生成心智云图失败: {str(e)}")
            else:
                # 没有五元组数据，提示用户
                chat.add_user_message("系统", "❌ 未找到五元组数据，请先进行对话以生成知识图谱")
        except Exception as e:
            chat.add_user_message("系统", f"❌ 打开心智云图失败: {str(e)}")

from ..utils.lazy import lazy
@lazy
def mindmap():
    return MindmapTool(config.window)