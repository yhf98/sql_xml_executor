
import os
import re
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from xml.etree import ElementTree as ET
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.encoders import jsonable_encoder
from typing import Dict, Any, List, Optional, Union

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class SqlXmlExecutor:
    def __init__(self, db: AsyncSession, mapper_dir: str = "mapper"):
        self.db = db
        self.queries = self.load_queries(mapper_dir)

    def load_queries(self, dir_path: str) -> Dict[str, Dict[str, str]]:
        queries = {}
        for filename in os.listdir(dir_path):
            if filename.endswith('.xml'):
                module = filename.split('.')[0]
                file_path = os.path.join(dir_path, filename)
                tree = ET.parse(file_path)
                root = tree.getroot()
                queries[module] = {}
                for query in root.findall('query'):
                    query_id = query.get('id')
                    # 提取整个 <query> 标签内的完整内容（含子标签）
                    query_text = self._get_full_query_text(query).strip()
                    queries[module][query_id] = query_text
        return queries

    def _get_full_query_text(self, element):
        """
        递归获取元素及其所有子元素的文本内容
        """
        text = element.text or ""
        for child in element:
            text += self._get_full_query_text(child)
        text += element.tail or ""
        return text

    def parse_xml_query(self, xml_query: str, params: dict) -> str:
        wrapped = f"<root>{xml_query}</root>"
        try:
            root = ET.fromstring(wrapped)
        except ET.ParseError as e:
            raise ValueError(f"XML 解析失败: {e}")

        def process_node(node):
            sql_parts = []
            for child in node:
                if child.tag == "if":
                    condition = child.attrib["test"]
                    if eval_condition(condition, params):
                        content = child.text.strip() if child.text else ""
                        sql_parts.append(content)
                elif child.tag == "where":
                    where_sql = process_node(child)
                    if where_sql:
                        sql_parts.append("WHERE " + where_sql)
                elif child.tag == "choose":
                    for when in child.findall("when"):
                        cond = when.attrib["test"]
                        if eval_condition(cond, params):
                            content = when.text.strip() if when.text else ""
                            sql_parts.append(content)
                            break
                else:
                    inner = process_node(child)
                    if inner:
                        sql_parts.append(inner)
            return "\n".join(sql_parts)

        def eval_condition(condition: str, params: dict) -> bool:
            return condition in params and params[condition] is not None

        raw_sql = re.sub(r'\s+AND\s', '\n  AND ', process_node(root), flags=re.IGNORECASE).strip()
        return raw_sql.replace("&gt;", ">").replace("&lt;", "<")

    async def execute(
        self,
        module: str,
        query_id: str,
        params: Optional[Dict[str, Any]] = None,
        single_row: bool = False,
        v_return_obj: bool = True,
        schema: Any = None
    ) -> Union[List[Dict], Dict, None]:
        if module not in self.queries or query_id not in self.queries[module]:
            raise ValueError(f"Query ID '{query_id}' not found in module '{module}'")

        raw_xml = self.queries[module][query_id]

        # 如果没有 <if>、<where> 等标签，直接执行原始 SQL
        if "<if" not in raw_xml and "<where" not in raw_xml:
            final_sql = raw_xml.replace("&gt;", ">").replace("&lt;", "<")
            
            # 🔍 打印 SQL 和参数
            logger.info(f"[SQL Query] Module: {module}, Query ID: {query_id}")
            logger.info(f"Final SQL:\n{final_sql}")
            logger.info(f"Params: {params}")

            result = await self.db.execute(text(final_sql), params or {})
            rows = result.mappings().all()
            if not rows:
                return None

            data = [dict(row) for row in rows]
            if v_return_obj and schema:
                data = [schema(**item) for item in data]
            return data[0] if single_row else data

        # 否则才走 XML 动态解析逻辑（如果需要的话）
        final_sql = self.parse_xml_query(raw_xml, params or {})

        # 🔍 打印解析后的 SQL 和参数
        logger.info(f"[SQL Query] Module: {module}, Query ID: {query_id}")
        logger.info(f"Parsed SQL:\n{final_sql}")
        logger.info(f"Params: {params}")

        result = await self.db.execute(text(final_sql), params or {})
        rows = result.mappings().all()

        if not rows:
            return None

        data = [dict(row) for row in rows]
        if v_return_obj and schema:
            data = [schema(**item) for item in data]
        return data[0] if single_row else data